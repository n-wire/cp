from amqtt.broker import Broker
from amqtt.session import Session
from config import mongo_client

class NodeWireBroker(Broker):
    def __init__(self, config=None, loop=None, plugin_namespace=None, handle_msg = None):
        self.handle_msg = handle_msg
        self.access_allowed = None
        self.messages = None
        self.db = mongo_client.nodewire
        self.new_client = None
        super().__init__(config, loop, plugin_namespace)

    async def client_connected(self, listener_name, reader, writer):
        await self.new_client(listener_name, reader, writer)
        
    async def loop(self, listener_name, reader, writer):
        await super().client_connected(listener_name, reader, writer)

    async def authenticate(self, session: Session, listener):
        if not session.username or not session.password:
            return False
        d_user = await self.db.users.find_one({'email': session.username}, {'layout': 0})
        if d_user and d_user['password'] == session.password:
            session.instanceid = d_user['instance']
            return True
        return False

    async def topic_filtering(self, session: Session, topic):
        words = topic.split('/')
        if not hasattr(session, 'instanceid'):
            session.instanceid = words[0]
        if not hasattr(session, 'nodename'):
            session.nodename = session.username
        if len(words) < 3:
            if words[0] == session.instanceid or words[0] == 'nodewire':
                return True
            else:
                return False
        permission = True # = await self.access_allowed(session.instanceid+":"+session.username, words[0]+':'+words[1], words[-1])
        if permission and hasattr(session, 'nodename') and len(words) == 3 and not (words[0] == session.instanceid and words[1] == session.nodename):
            self.messages.put_nowait(('{}:cp subscribe {} val {}:{}\n'.format(words[0], words[1], session.instanceid, session.nodename), self.task))
            print('{}:cp subscribe {} val {}:{}\n'.format(words[0], words[1], session.instanceid, session.nodename))
        return permission

    async def _broadcast_message(self, session, topic, data, force_qos=None):
        # overridden to intercept mqtt messages and send to cp
        broadcast = {
            'session': session,
            'topic': topic,
            'data': data
        }
        await self.handle_msg(topic, data, session)
        if force_qos:
            broadcast['qos'] = force_qos
        await self._broadcast_queue.put(broadcast)

    async def send_message(self, session, topic, data, force_qos=None):
        # messages from cp to mqtt
        broadcast = {
            'session': session,
            'topic': topic,
            'data': data
        }
        if force_qos:
            broadcast['qos'] = force_qos
        await self._broadcast_queue.put(broadcast)

    async def _stop_handler(self, handler):
        try:
            #self.close()
            await handler.stop()
        except Exception as e:
            self.logger.error(e)
