import asyncio
from message import Message
from socket_link import SocketLink
import motor.motor_asyncio

from db import mongo_client

class cp:
    def __init__(self):
        self.sys_db = mongo_client.nodewire
        self.clients = []
        self.messages = asyncio.Queue()

        self.socket = SocketLink(self.messages)
        self.socket.new = self.client_added
        self.socket.client_done = self.client_closed

        self.pipe = SocketLink(self.messages, port=9001)
        self.pipe.new = self.client_added
        self.pipe.client_done = self.client_closed
        self.pipe.safe = True

    def client_added(self, client):
        if client in self.clients:
            self.client_closed(client)
        self.clients.append(client)

    def client_closed(self, client):
        try:
            clients = [c for c in self.clients if c == client]
            if len(clients)!=0:
                client = clients[0]
                self.re_remove_nodes(client)
                if client in self.clients:
                    self.clients.remove(client)

                # update number of connected gateways
                n = len([c for c in self.clients if c['gateway'] == client['gateway']])
                n_g = {'instance': client['gateway'], 'count': n}

                asyncio.get_event_loop().call_soon(self.sys_db.live_gateways.replace_one, {'instance': client['gateway']}, n_g)
        except Exception as ex:
            print('pass 7'),
            print(ex)

    async def handle(self, message):
        pass

    async def forward(self, client, message):
        pass

    async def run_async(self):
        await asyncio.gather(
            asyncio.ensure_future(self.socket.start()),
            asyncio.ensure_future(self.pipe.start()),
            asyncio.ensure_future(self.process())
        )

    def run(self):
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(self.run_async())
            loop.run_forever()
        except KeyboardInterrupt:
            # Canceling pending tasks and stopping the loop
            # asyncio.gather(*asyncio.all_tasks()).cancel()
            #loop.stop()
            loop.run_until_complete(loop.shutdown_asyncgens())
            #loop.close()

    async def process(self):
        while True:
            raw, sender = await self.messages.get()
            message = Message(raw)
            if message.address == 'cp':
                await self.handle(message)
            elif message.address in ['ee', 'db']:
                pass
            else:
                clients = [c for c in clients if c.address == message.address and c.instance==message.address_instance]
                if clients:
                    self.forward(clients[0], message)




if __name__ == "__main__":
    the_cp = cp()
    the_cp.run()