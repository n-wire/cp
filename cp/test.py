from admin import Admin
import unittest
from message import Message
from cp import CommandProcessor
import asyncio
import motor.motor_asyncio

class TestPlainTalk(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_boolean(self):
        msg = Message('cp val led true node')
        self.assertEqual(msg.value, True)

    def test_number(self):
        msg = Message('cp val led 1 node')
        self.assertEqual(msg.value, 1)

    def test_string(self):
        msg = Message('cp val led "on" node')
        self.assertEqual(msg.value, 'on')

    def test_object(self):
        msg = Message('cp val led {"state":"on"} node')
        self.assertEqual(msg.value, {"state":"on"})

    def test_split(self):
        msg = Message('adasd:cp val led 1 addasA:node')
        self.assertEqual(msg.address, 'cp')
        self.assertEqual(msg.address_instance, 'adasd')
        self.assertEqual(msg.command, 'val')
        self.assertEqual(msg.port, 'led')
        self.assertEqual(msg.value, 1)
        self.assertEqual(msg.sender, 'node')
        self.assertEqual(msg.sender_instance, 'addasA')

class TestServer(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.the_cp = CommandProcessor()
        asyncio.Task(self.the_cp.run_async())

    async def test_connected(self):
        await asyncio.sleep(1)
        self.assertEqual(len(self.the_cp.clients), 0)
        self.reader, self.writer = await asyncio.open_connection('localhost', 9001)
        self.assertEqual(len(self.the_cp.clients), 1)
        self.writer.write('')
        self.writer.close()

    async def asyncTearDown(self):
        for task in asyncio.all_tasks():
            task.cancel()
    
    def tearDown(self) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

if __name__ == '__main__':
    unittest.main()