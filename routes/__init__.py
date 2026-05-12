from routes.auth import register_routes as register_auth_routes
from routes.posts import register_routes as register_post_routes
from routes.profiles import register_routes as register_profile_routes
from routes.stories import register_routes as register_story_routes
from routes.messages import register_routes as register_message_routes
from routes.communities import register_routes as register_community_routes
from routes.music import register_routes as register_music_routes
from routes.bots import register_routes as register_bot_routes


def register_all_routes(app):
    register_auth_routes(app)
    register_post_routes(app)
    register_profile_routes(app)
    register_story_routes(app)
    register_message_routes(app)
    register_community_routes(app)
    register_music_routes(app)
    register_bot_routes(app)
