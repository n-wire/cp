from link import Link
import asyncio
import websockets
import random, string


class WebLink(Link):
    def __init__(self, messages, address='0.0.0.0', port = 5005) -> None:
        super().__init__(messages)
        self.type = 'web'
        self.address = address
        self.port = port
        self.session = ''.join(random.choice(string.ascii_lowercase) for i in range(5))

    def start(self):
        return websockets.serve(self.loop, self.address, self.port)

    '''async def authenticated(self):
        if await super().authenticated():
            self.nodes.append(self.user['email'])
            return True
        return False'''

    async def loop(self, websocket, path):
        the_link = WebLink(self.messages)
        the_link.reader = websocket
        the_link.writer =  websocket
        the_link.client_done = self.client_done
        the_link.new = self.new
        the_link.task = asyncio.current_task()
        the_link.task.add_done_callback(the_link.client_done)
        await the_link.main_loop()

    async def send(self, data):
        await self.writer.send(f'{data}\r\n')

    async def receive(self):
        return (await self.reader.recv())

    def close(self):
        asyncio.Task(self.writer.close())