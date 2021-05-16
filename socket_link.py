from link import Link
import asyncio


class SocketLink(Link):
    def __init__(self, messages, address='0.0.0.0', port = 10001) -> None:
        super().__init__(messages)
        self.address = address
        self.port = port

    def start(self):
        return asyncio.start_server(self.accept_client, self.address, self.port)

    def accept_client(self, client_reader, client_writer):
        the_link = SocketLink(self.messages)
        the_link.reader = client_reader
        the_link.writer =  client_writer
        the_link.client_done = self.client_done
        the_link.safe = self.safe
            
        if self.new: self.new(the_link)
        task = asyncio.Task(the_link.loop(client_reader, client_writer))
        task.add_done_callback(the_link.client_done)

    async def loop(self, client_reader, client_writer):
        await self.main_loop()

    async def send(self, data):
        self.writer.write(f'{data}\n'.encode())
        await self.writer.drain()

    async def receive(self):
        return (await self.reader.readline()).decode('utf8')

    def close(self):
        self.writer.close()