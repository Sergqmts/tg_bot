let callSocket = null;
let callPeerConnection = null;
let callLocalStream = null;
let callRemoteStream = null;
let currentCallId = null;
let currentCallType = null;
let callActive = false;
let callMuted = false;
let callCameraOff = false;
let callScreenShared = false;
let callStartTime = null;
let callTimerInterval = null;
let pendingCallData = null;
let iceCandidateQueue = [];
let wsMessageQueue = [];
let wsRetryTimeout = null;
let wsRetryDelay = 1000;
let wsPingInterval = null;

const WS_URL = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/call';
const ICE_SERVERS = {
    iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
        { urls: 'stun:stun2.l.google.com:19302' },
        { urls: 'stun:stun3.l.google.com:19302' },
        { urls: 'stun:stun4.l.google.com:19302' },
    ]
};

function wsSend(data) {
    if (callSocket && callSocket.readyState === WebSocket.OPEN) {
        callSocket.send(JSON.stringify(data));
    } else if (callSocket && callSocket.readyState === WebSocket.CONNECTING) {
        wsMessageQueue.push(data);
    }
}

function flushWsQueue() {
    while (wsMessageQueue.length) {
        var msg = wsMessageQueue.shift();
        if (callSocket && callSocket.readyState === WebSocket.OPEN) {
            callSocket.send(JSON.stringify(msg));
        }
    }
}

function connectCallWS(userId) {
    if (callSocket && callSocket.readyState === WebSocket.OPEN) return;
    if (callSocket) { callSocket.onclose = null; callSocket.close(); }
    if (wsRetryTimeout) { clearTimeout(wsRetryTimeout);
        wsRetryTimeout = null; }
    callSocket = new WebSocket(WS_URL);
    callSocket.onopen = function () {
        wsRetryDelay = 1000;
        if (wsPingInterval) { clearInterval(wsPingInterval); }
        wsPingInterval = setInterval(function () {
            if (callSocket && callSocket.readyState === WebSocket.OPEN) {
                callSocket.send(JSON.stringify({ type: 'ping' }));
            }
        }, 15000);
        wsSend({ type: 'auth', user_id: userId });
        flushWsQueue();
        if (callActive && currentCallId) {
            wsSend({
                type: 'call:rejoin',
                data: { call_id: currentCallId }
            });
        }
    };
    callSocket.onmessage = function (ev) {
        var msg = JSON.parse(ev.data);
        handleWSMessage(msg);
    };
    callSocket.onclose = function () {
        if (wsPingInterval) { clearInterval(wsPingInterval);
            wsPingInterval = null; }
        wsRetryDelay = Math.min(wsRetryDelay * 2, 30000);
        wsRetryTimeout = setTimeout(function () { connectCallWS(userId); }, wsRetryDelay);
    };
}

function handleWSMessage(msg) {
    switch (msg.type) {
        case 'call:incoming':
            showIncomingCall(msg.data);
            break;
        case 'call:initiated':
            break;
        case 'call:answered':
            onCallAnswered(msg.data);
            break;
        case 'call:declined':
            onCallDeclined(msg.data);
            break;
        case 'call:ended':
            onRemoteEnded(msg.data);
            break;
        case 'sdp:offer':
            handleSDPOffer(msg.data);
            break;
        case 'sdp:answer':
            handleSDPAnswer(msg.data);
            break;
        case 'ice:candidate':
            handleICECandidate(msg.data);
            break;
        case 'call:peer_mute':
            updatePeerMuteStatus(msg.data);
            break;
        case 'call:peer_camera':
            updatePeerCameraStatus(msg.data);
            break;
        case 'auth:ok':
            break;
        case 'ping':
            wsSend({ type: 'pong' });
            break;
        case 'pong':
            break;
        case 'error':
            console.error('WS error:', msg.message);
            if (currentCallId) {
                fetch('/api/calls/' + currentCallId + '/end', {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCSRFToken() }
                }).catch(function () { });
            }
            if (callActive) {
                stopCall();
                hideCallScreen();
            }
            alert(msg.message || 'Ошибка вызова');
            break;
    }
}

async function initiateCall(calleeId, calleeUsername, callType) {
    if (callActive) return;
    currentCallType = callType;

    try {
        var resp = await fetch('/api/calls/initiate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
            body: JSON.stringify({ callee_id: calleeId, call_type: callType })
        });
        var data = await resp.json();
        if (!resp.ok) { alert(data.error || 'Call failed'); return; }

        currentCallId = data.call_id;
        wsSend({
            type: 'call:initiate',
            data: {
                callee_id: calleeId,
                call_id: currentCallId,
                call_type: callType,
                caller_username: window.currentUsername
            }
        });

        showCallScreen('calling', calleeUsername, callType);
        callStartTime = Date.now();
    } catch (e) {
        console.error('Initiate call error:', e);
    }
}

async function answerCall() {
    if (!pendingCallData) return;
    var data = pendingCallData;
    hideIncomingCall();
    currentCallId = data.call_id;
    currentCallType = data.call_type;

    showCallScreen('connecting', data.caller_username, data.call_type);

    await startLocalStream(currentCallType);
    createPeerConnection();
    callActive = true;
    startCallTimer();

    wsSend({
        type: 'call:answer',
        data: { call_id: currentCallId }
    });
}

function declineCall() {
    if (!pendingCallData) return;
    wsSend({
        type: 'call:decline',
        data: { call_id: pendingCallData.call_id }
    });
    hideIncomingCall();
    pendingCallData = null;
}

async function onCallAnswered(data) {
    await startLocalStream(currentCallType);
    createPeerConnection();
    callActive = true;
    startCallTimer();
    updateCallScreenStatus('connected');

    var offer = await callPeerConnection.createOffer();
    await callPeerConnection.setLocalDescription(offer);
    wsSend({
        type: 'sdp:offer',
        data: { call_id: currentCallId, sdp: offer }
    });
}

function onCallDeclined(data) {
    stopCall();
    updateCallScreenStatus('declined');
    setTimeout(hideCallScreen, 1500);
}

function onRemoteEnded(data) {
    stopCall();
    updateCallScreenStatus('ended');
    setTimeout(hideCallScreen, 1000);
}

async function handleSDPOffer(data) {
    if (!callPeerConnection) createPeerConnection();
    try {
        await callPeerConnection.setRemoteDescription(data.sdp);
        flushIceCandidateQueue();
        var answer = await callPeerConnection.createAnswer();
        await callPeerConnection.setLocalDescription(answer);
        wsSend({
            type: 'sdp:answer',
            data: { call_id: currentCallId, sdp: answer }
        });
    } catch (e) {
        console.error('SDP offer error:', e);
    }
}

async function handleSDPAnswer(data) {
    if (!callPeerConnection || callPeerConnection.remoteDescription) return;
    try {
        await callPeerConnection.setRemoteDescription(data.sdp);
        flushIceCandidateQueue();
    } catch (e) {
        console.error('SDP answer error:', e);
    }
}

function handleICECandidate(data) {
    if (!data.candidate) return;
    if (!callPeerConnection || !callPeerConnection.remoteDescription) {
        iceCandidateQueue.push(data.candidate);
        return;
    }
    callPeerConnection.addIceCandidate(new RTCIceCandidate(data.candidate)).catch(function (e) { });
}

function flushIceCandidateQueue() {
    while (iceCandidateQueue.length) {
        callPeerConnection.addIceCandidate(new RTCIceCandidate(iceCandidateQueue.shift())).catch(function (e) { });
    }
}

function createPeerConnection() {
    callPeerConnection = new RTCPeerConnection(ICE_SERVERS);
    if (callLocalStream) {
        callLocalStream.getTracks().forEach(function (t) {
            callPeerConnection.addTrack(t, callLocalStream);
        });
    }
    callPeerConnection.ontrack = function (ev) {
        callRemoteStream = ev.streams[0];
        var vid = document.getElementById('remoteVideo');
        if (vid) {
            vid.srcObject = callRemoteStream;
            vid.play().catch(function (e) { });
        }
    };
    callPeerConnection.onicecandidate = function (ev) {
        if (ev.candidate) {
            wsSend({
                type: 'ice:candidate',
                data: { call_id: currentCallId, candidate: ev.candidate }
            });
        }
    };
    callPeerConnection.onconnectionstatechange = function () {
        if (callPeerConnection.connectionState === 'disconnected' ||
            callPeerConnection.connectionState === 'failed') {
            if (callActive) {
                fetch('/api/calls/' + currentCallId + '/end', {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCSRFToken() }
                }).catch(function () { });
                stopCall();
                updateCallScreenStatus('ended');
                setTimeout(hideCallScreen, 1000);
            }
        }
    };
}

async function startLocalStream(callType) {
    try {
        var constraints = {
            audio: true,
            video: callType === 'video'
        };
        callLocalStream = await navigator.mediaDevices.getUserMedia(constraints);
        var vid = document.getElementById('localVideo');
        if (vid) {
            vid.srcObject = callLocalStream;
            vid.muted = true;
        }
        document.getElementById('localVideoContainer').classList.remove('hidden');
    } catch (e) {
        console.error('Media error:', e);
        if (callType === 'video') {
            currentCallType = 'audio';
            return startLocalStream('audio');
        }
        if (e.name === 'NotFoundError' || e.name === 'NotAllowedError') {
            alert('Не найден микрофон. Разрешите доступ к микрофону в настройках браузера.');
        }
    }
}

function endCall() {
    wsSend({
        type: 'call:end',
        data: { call_id: currentCallId }
    });
    fetch('/api/calls/' + currentCallId + '/end', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCSRFToken() }
    }).catch(function () { });
    stopCall();
    hideCallScreen();
}

function stopCall() {
    callActive = false;
    if (callTimerInterval) { clearInterval(callTimerInterval);
        callTimerInterval = null; }
    if (wsPingInterval) { clearInterval(wsPingInterval);
        wsPingInterval = null; }
    if (callPeerConnection) { callPeerConnection.close();
        callPeerConnection = null; }
    if (callLocalStream) {
        callLocalStream.getTracks().forEach(function (t) { t.stop(); });
        callLocalStream = null;
    }
    callRemoteStream = null;
    currentCallId = null;
    currentCallType = null;
    pendingCallData = null;
    iceCandidateQueue = [];
    wsMessageQueue = [];
    if (wsRetryTimeout) { clearTimeout(wsRetryTimeout);
        wsRetryTimeout = null; }
    callMuted = false;
    callCameraOff = false;
    callScreenShared = false;
    document.getElementById('localVideoContainer').classList.add('hidden');
    var rv = document.getElementById('remoteVideo');
    if (rv) rv.srcObject = null;
    var lv = document.getElementById('localVideo');
    if (lv) lv.srcObject = null;
}

function toggleMute() {
    callMuted = !callMuted;
    if (callLocalStream) {
        callLocalStream.getAudioTracks().forEach(function (t) { t.enabled = !callMuted; });
    }
    wsSend({
        type: 'call:toggle_mute',
        data: { call_id: currentCallId, muted: callMuted }
    });
    updateMuteButton();
}

function toggleCamera() {
    if (currentCallType !== 'video') return;
    callCameraOff = !callCameraOff;
    if (callLocalStream) {
        callLocalStream.getVideoTracks().forEach(function (t) { t.enabled = !callCameraOff; });
    }
    wsSend({
        type: 'call:toggle_camera',
        data: { call_id: currentCallId, camera_on: !callCameraOff }
    });
    updateCameraButton();
}

function toggleSpeaker() {
    var vid = document.getElementById('remoteVideo');
    if (vid) {
        vid.sinkId = vid.sinkId ? '' : undefined;
    }
}

function togglePip() {
    var vid = document.getElementById('remoteVideo');
    if (!vid) return;
    if (document.pictureInPictureElement) {
        document.exitPictureInPicture().catch(function () { });
    } else {
        vid.requestPictureInPicture().catch(function () { });
    }
}

function toggleScreenShare() {
    if (callScreenShared) {
        stopScreenShare();
    } else {
        startScreenShare();
    }
}

async function startScreenShare() {
    try {
        var stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
        var sender = callPeerConnection.getSenders().find(function (s) {
            return s.track && s.track.kind === 'video';
        });
        if (sender) {
            sender.replaceTrack(stream.getVideoTracks()[0]);
        }
        callScreenShared = true;
        var lv = document.getElementById('localVideo');
        if (lv) lv.srcObject = stream;
        stream.getVideoTracks()[0].onended = function () { stopScreenShare(); };
    } catch (e) { }
}

function stopScreenShare() {
    if (!callScreenShared) return;
    callScreenShared = false;
    if (callLocalStream) {
        var sender = callPeerConnection.getSenders().find(function (s) {
            return s.track && s.track.kind === 'video';
        });
        if (sender) {
            sender.replaceTrack(callLocalStream.getVideoTracks()[0]);
        }
        var lv = document.getElementById('localVideo');
        if (lv) lv.srcObject = callLocalStream;
    }
}

function startCallTimer() {
    callStartTime = Date.now();
    callTimerInterval = setInterval(function () {
        var el = document.getElementById('callTimer');
        if (!el) return;
        var diff = Math.floor((Date.now() - callStartTime) / 1000);
        var m = Math.floor(diff / 60);
        var s = diff % 60;
        el.textContent = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }, 1000);
}

function getCSRFToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
    var input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : '';
}

function showIncomingCall(data) {
    pendingCallData = data;
    var modal = document.getElementById('incomingCallModal');
    if (!modal) return;
    document.getElementById('incomingCallerName').textContent = data.caller_username || 'Unknown';
    document.getElementById('incomingCallType').textContent = data.call_type === 'video' ? 'Видеозвонок' : 'Аудиозвонок';
    modal.classList.remove('hidden');
    if (data.call_type === 'video') {
        document.getElementById('incomingCallType').textContent = '📹 Видеозвонок';
    } else {
        document.getElementById('incomingCallType').textContent = '📞 Аудиозвонок';
    }
    playRingtone();
}

function hideIncomingCall() {
    var modal = document.getElementById('incomingCallModal');
    if (modal) modal.classList.add('hidden');
    stopRingtone();
}

function showCallScreen(mode, peerName, callType) {
    var screen = document.getElementById('callScreen');
    if (!screen) return;
    screen.classList.remove('hidden');

    document.getElementById('callPeerName').textContent = peerName || 'Unknown';
    document.getElementById('callStatus').textContent = mode === 'calling' ? 'Звоним...' : mode === 'connecting' ? 'Подключение...' : '';

    if (callType === 'video') {
        document.getElementById('callScreenType').textContent = '📹';
        document.getElementById('callScreenVideoArea').classList.remove('hidden');
        document.getElementById('callScreenAudioOnly').classList.add('hidden');
    } else {
        document.getElementById('callScreenType').textContent = '📞';
        document.getElementById('callScreenVideoArea').classList.add('hidden');
        document.getElementById('callScreenAudioOnly').classList.remove('hidden');
    }

    var rv = document.getElementById('remoteVideo');
    if (rv) {
        rv.style.display = callType === 'video' ? 'block' : 'none';
    }
    document.getElementById('localVideoContainer').style.display = callType === 'video' ? 'block' : 'none';
    if (callType === 'video') {
        document.getElementById('cameraBtn').style.display = 'flex';
    } else {
        document.getElementById('cameraBtn').style.display = 'none';
    }
}

function hideCallScreen() {
    var screen = document.getElementById('callScreen');
    if (screen) screen.classList.add('hidden');
    stopCall();
}

function updateCallScreenStatus(status) {
    var el = document.getElementById('callStatus');
    if (!el) return;
    var msgs = { connected: 'Разговор', ended: 'Звонок завершен', declined: 'Отменен' };
    el.textContent = msgs[status] || status;
}

function updateMuteButton() {
    var btn = document.getElementById('muteBtn');
    if (!btn) return;
    btn.classList.toggle('active', callMuted);
    btn.innerHTML = callMuted ? '<i class="fa-solid fa-microphone-slash"></i>' : '<i class="fa-solid fa-microphone"></i>';
}

function updateCameraButton() {
    var btn = document.getElementById('cameraBtn');
    if (!btn) return;
    btn.classList.toggle('active', callCameraOff);
    btn.innerHTML = callCameraOff ? '<i class="fa-solid fa-video-slash"></i>' : '<i class="fa-solid fa-video"></i>';
}

function updatePeerMuteStatus(data) {
    var el = document.getElementById('peerMuteIndicator');
    if (el) el.style.display = data.muted ? 'block' : 'none';
}

function updatePeerCameraStatus(data) {
    var el = document.getElementById('peerCameraIndicator');
    if (el) el.style.display = data.camera_on ? 'none' : 'block';
}

var ringtoneCtx = null;
var ringtoneGain = null;
var ringtoneOsc = null;

function playRingtone() {
    try {
        if (!ringtoneCtx) {
            ringtoneCtx = new (window.AudioContext || window.webkitAudioContext)();
            ringtoneGain = ringtoneCtx.createGain();
            ringtoneGain.gain.value = 0.3;
            ringtoneGain.connect(ringtoneCtx.destination);
        }
        var freq = 440;
        ringtoneOsc = ringtoneCtx.createOscillator();
        ringtoneOsc.type = 'sine';
        ringtoneOsc.frequency.value = freq;
        ringtoneOsc.connect(ringtoneGain);
        ringtoneOsc.start();
        var onOff = true;
        ringtoneOsc.interval = setInterval(function () {
            onOff = !onOff;
            ringtoneGain.gain.value = onOff ? 0.3 : 0;
        }, 500);
    } catch (e) { }
}

function stopRingtone() {
    try {
        if (ringtoneOsc) {
            clearInterval(ringtoneOsc.interval);
            ringtoneOsc.stop();
            ringtoneOsc.disconnect();
            ringtoneOsc = null;
        }
        if (ringtoneCtx) {
            ringtoneCtx.close();
            ringtoneCtx = null;
        }
    } catch (e) { }
}

// PiP close handler
if (typeof document !== 'undefined') {
    document.addEventListener('pictureInPictureClosed', function () { });
}
