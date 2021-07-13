from sanic import Sanic
from sanic.response import json, text, html
from auth import protected, login
import string
import random
from admin import Admin
from pymongo.errors import DuplicateKeyError
import asyncio
from message import Message


app = Sanic("NodeWire")

app.config.SECRET = "this is my secret"
app.blueprint(login)
app.ctx.db = Admin()
app.static("/static", "/static")

writer = None
reader = None

@app.listener("before_server_start")
async def setup(app, loop):
    global reader, writer
    try:
        reader, writer = await asyncio.open_connection('localhost', 9001)
        print('NodeWire Rest Server started')
    except:
        pass
    

@app.route('/')
async def home(request):
    f = open('index.html')
    return html(f.read())

@app.get("/node/<nodename:string>/<port:string>")
@protected
async def node_get(request, nodename:str, port:str):
    print(f'{request.ctx.instance}:{nodename} get {port} {request.ctx.user}')
    reader.read
    writer.write(f'{request.ctx.instance}:{nodename} get {port} {request.ctx.user}\n'.encode())
    await writer.drain()
    raw = (await reader.readline()).decode('utf8')
    print(raw)
    if raw:
        val = Message(raw)
        print(val.value)
        return json(val.value)
    return(json(None))

@app.post("/node/<nodename:string>/<port:string>")
@protected
async def node_post(request, nodename:str, port:str):
    print(f'{request.ctx.instance}:{nodename} set {port} {request.json} {request.ctx.user}')
    writer.write(f'{request.ctx.instance}:{nodename} set {port} {request.json} {request.ctx.user}\n'.encode())
    await writer.drain()
    return text('success')

def id_generator(size=12, chars=string.ascii_lowercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))

@app.post("/createUser")
async def create_user(request):
    if 'name' in request.json and 'email' in request.json and 'password' in request.json:
        try:
            app.ctx.db.create_instance(id_generator(), {'fullname': request.json["name"], 'email': request.json["email"], 'password': request.json["password"]})
        except DuplicateKeyError:
            return text('user exists already')

        return text('success')
    else:
        return text('failed')

@app.post('/add_gateway')
@protected
async def add_gateway(request):
    result = app.ctx.db.add_gateway(request.ctx.user, request.json['gateway'])
    if result == True:
        return text('success')
    else:
        return text('failed')

@app.post('/del_gateway')
@protected
async def del_gateway(request):
    user = request.json
    if app.ctx.db.del_gateway(request.ctx.user, user['gateway']):
        return text('success')
    else:
        return text('failed')

@app.post('/register')
@protected
async def register(request):
    writer.write(f'{request.ctx.instance}:cp set id {request.json["nodename"]} {request.json["id"]} {request.json["nodename"]} {request.ctx.user}\n'.encode())
    writer.write(f'{request.ctx.instance}:cp register {request.json["nodename"]} {request.json["id"]} pwd={request.json["pwd"]} {request.ctx.user}\n'.encode())
    await writer.drain()
    reader.readline()


if __name__ == '__main__':
    app.run()