from functools import wraps

import jwt
from sanic import Blueprint, text

login = Blueprint("login", url_prefix="/login")



@login.post("/")
async def do_login(request):
    token = request.app.ctx.db.get_token(request.json["email"])
    return text(token)


def check_token(request):
    if not request.token:
        return False
    try:
        json = jwt.decode(
            request.token, request.app.config.SECRET, algorithms=["HS256"]
        )
        request.ctx.user = json['email']
        request.ctx.instance = json['instance']
    except jwt.exceptions.InvalidTokenError:
        return False
    else:
        return True


def protected(wrapped):
    def decorator(f):
        @wraps(f)
        async def decorated_function(request, *args, **kwargs):
            is_authenticated = check_token(request)

            if is_authenticated:
                response = await f(request, *args, **kwargs)
                return response
            else:
                return text("You are unauthorized.", 401)

        return decorated_function

    return decorator(wrapped)