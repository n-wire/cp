from enum import unique
from pymongo import MongoClient
from bson.objectid import ObjectId
import random
#from nodewire.getip import connectedip
import time
import string
from sanic import Sanic
import jwt

try:
    import cp.myemail
except:
    myemail = None


from config import nw_server


class Admin():
    def __init__(self):
        global app
        app = Sanic.get_app("NodeWire")
        self.mongo = MongoClient(nw_server, 27017)
        self.data = self.mongo.nodewire
        if self.data.users.find_one({}) == None:
            # create data 
            self.data.users.create_index([('email', 1)], unique = True, background = True)

    def get_token(self, email):
        user = self.data.users.find_one({'email': email})
        return jwt.encode({"email": user['email'], 'instance':user['instance']}, app.config.SECRET)

    def create_user(self, email,  password, instance, fullname):
        user = {
            'email': email,
            'fullname': fullname,
            'instance': instance,
            'password': password,
            'tokens': [], # {id, token}
            'trust_zones': [instance, ],
            'gateways': [],
            'layout': {},  # current app
            'apps': []  # list of app_ids
        }
        users = self.data.users
        inserted_id =  users.insert_one(user).inserted_id
        token = self.get_token(email)
        try:
            if myemail:
                myemail.send({
                    "receiver": email,
                    "subject": "NodeWire Account Creation",
                    "body": f'''Dear {fullname}<br><br>
                    
                    The NodeWire Account, {email}, has been created.<br><br>
                    
                    Your instance id is {instance}. <br><br>
                    
                    Please click on the link within one hour to confirm your account:
                    <a href="http://dashboard.nodewire.org/?tok={token}">Dashboard</a><br><br>
                    
                    Regards<br><br>
                    
                    NodeWire
                    '''
                })

                myemail.send({
                    "receiver": 'sadiq.a.ahmad@gmail.com',
                    "subject": "NodeWire Account Creation",
                    "body": f'''Dear {fullname}<br><br>
                    
                    The NodeWire Account, {email}, has been created.<br><br>
                    
                    Your instance id is {instance}. <br><br>
                    
                    Please click on the link within one hour to confirm your account:
                    <a href="http://dashboard.nodewire.org/?tok={token}">Dashboard</a><br><br>
                    
                    Regards<br><br>
                    
                    NodeWire
                    '''
                })
        except Exception as ex:
            pass

        return inserted_id

    def create_instance(self, instance_address, user):
        userid = self.create_user(user['email'], user['password'], instance_address, user['fullname'])
        instance = {
            'instance_id': instance_address,
            'owner': ObjectId(userid),
            'registered_nodes': [],
            'users':[{'user_instance_and_node_name': '{}:{}'.format(instance_address, user['email']), 'admin':  True}],
            'layouts':[], # list of layout ids each layout is stored in the layout collection: title, icon, layout, sketch, script
        }
        instances = self.data.instances
        instances.insert_one(instance)

    def add_user(self, email, uinstance, uemail, uadmin):
        user = self.data.users.find_one({'email': email})
        instance = self.data.instances.find_one({'instance_id': user['instance']})
        fullname = uinstance+':'+uemail
        if instance['owner'] == user['_id']:
            duser = self.data.users.find_one({'email': uemail})
            if duser==None and uinstance  == instance['instance_id']:
                self.create_user(uemail, 'secret', instance['instance_id'], 'No Name')
                instance['users'].append({'user_instance_and_node_name': '{}:{}'.format(uinstance, uemail), 'admin':  False})
                self.data.instances.update({'_id': instance['_id']}, instance)
                return instance['users']
            elif duser['instance'] == uinstance and fullname not in [u['user_instance_and_node_name'] for u in instance['users']]:
                instance['users'].append({'user_instance_and_node_name': '{}:{}'.format(uinstance, uemail), 'admin':  uadmin})
                self.data.instances.update({'_id': instance['_id']}, instance)
                duser['trust_zones'].append(user['instance'])
                self.data.users.update({'_id': duser['_id']}, duser)
                return instance['users']
        return False

    def delete_user(self, email, users):
        User = self.data.users.find_one({'email': email})
        instance = self.data.instances.find_one({'instance_id': User['instance']})
        if instance['owner']==User['_id']:
            for user in users:
                dusers = [u for u in instance['users'] if u['user_instance_and_node_name']==user]
                if len(dusers)!=0:
                    instance['users'].remove(dusers[0])
                    actuser = self.data.users.find_one({'email': dusers[0]['user_instance_and_node_name'].split(':')[1]})
                    actuser['trust_zones'].remove(User['instance'])
                    if actuser['trust_zones']!=[]:
                        self.data.users.update({'email': actuser['email']}, actuser)
                    else:
                        self.data.users.remove({'email': actuser['email']})
            self.data.instances.update({'_id': instance['_id']}, instance)
            return instance['users']
        return False

    def save_users(self, email, users):
        user = self.data.users.find_one({'email': email})
        instance = self.data.instances.find_one({'instance_id': user['instance']})
        if instance['owner'] == user['_id']:
            instance['users'] = users
            self.data.instances.update({'_id': instance['_id']}, instance)
            return True
        return False

    def add_gateway(self, email, gateway):
        user = self.data.users.find_one({'gateways': gateway})
        if user is None:
            user = self.data.users.find_one({'email': email})
            if 'gateways' not in user:
                user['gateways'] = []
            user['gateways'].append(gateway)
            self.data.users.update({'_id': user['_id']}, user)
            return True
        else:
            return 'already registered to ' + user['email']

    def del_gateway(self, email, gateway):
        user = self.data.users.find_one({'gateways': gateway, 'email': email})
        if not user is None:
            user['gateways'].remove(gateway)
            user['tokens'] = [tok for tok in user['tokens'] if tok['id'] != gateway]
            self.data.users.update({'_id': user['_id']}, user)
            return True
        else:
            return False

    def instance_delete_nodes(self, email,  nodes):
        user = self.data.users.find_one({'email': email})
        instance = self.data.instances.find_one({'instance_id': user['instance']})
        if self.is_admin(user, instance):
            for node in nodes:
                thenode = [n for n in instance['registered_nodes'] if n['id'] == node]
                instance['registered_nodes'].remove(thenode[0])
            self.data.instances.update({'_id': instance['_id']}, instance)
            return instance['registered_nodes']
        return False

    def instance_delete_all_nodes(self, email):
        user = self.data.users.find_one({'email': email})
        instance = self.data.instances.find_one({'instance_id': user['instance']})
        if self.is_admin(user, instance):
            instance['registered_nodes'] = []
            self.data.instances.update({'_id': instance['_id']}, instance)
            return True
        return False

    def instance_save_nodes(self, email, nodes):
        user = self.data.users.find_one({'email': email})
        instance = self.data.instances.find_one({'instance_id': user['instance']})
        if self.is_admin(user, instance):
            instance['registered_nodes'] = nodes
            self.data.instances.update({'_id': instance['_id']}, instance)
            return True
        return False

    def create_node(self, instance_id, node_name, node_id):
        node = {
            'name':node_name,
            'node_id': node_id,
            'access_permission': [2,2,1] # [admin, users, others], 0 no access, 1 read access, 2 read/write access
        }
        instances =self.data.instances
        instance = instances.find_one({'instance_id': instance_id})[0]
        found = [i for i in instance['registered_nodes'] if i['name'] == node_name]
        if len(found) != 0:
            instance['registered_nodes'].remove(found[0])
        instance['registered_nodes'].append(node)
        instances.update({'instance_id': instance_id}, instance)

    def get_user(self, email):
        users = self.data.users
        user = users.find_one({'email': email})
        return user

    def save_user(self, user):
        users = self.data.users
        users.update({'email': user['email']}, user)

    def is_admin(self, user,  instance):
        return len([u for u in instance['users'] if u['user_instance_and_node_name']==user['instance']+':'+user['email'] and u['admin']])!=0

    def get_config(self, email):
        user = self.data.users.find_one({'email': email})
        if user['instance'] == None:
            config = {'cp_address': '138.197.6.173', 'mqtt_address': 'cloud.nodewire.org', 'mqtt_tcp_port': '1883',
                      'mqtt_web_port': '8080'}
            iid = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(12))
            user["instance"] = iid
            user["trusted_zones"].insert(0, iid)
            instance = {
                'instance_id': iid,
                'owner': user["_id"],
                'registered_nodes': [],
                'users': [
                    {'user_instance_and_node_name': '{}:{}'.format(iid, user['email']), 'admin': True}],
                'layouts': [],
            # list of layout ids each layout is stored in the layout collection: title, icon, layout, sketch, script
                'config': config
            }
            instances = self.data.instances
            instances.insert_one(instance)
        user['last_seen'] = time.time()
        self.data.users.update({'email': email}, user)
        instance = self.data.instances.find_one({'instance_id': user['instance']})
        server = self.determine_server(user['instance'])
        is_admin = len([u for u in instance['users'] if u['user_instance_and_node_name']==user['instance']+':'+email and u['admin']])!=0
        if instance['config']['cp_address'] != server:
            instance['config']['cp_address'] = server
            #del instance['_id']
            self.data.instances.update({'instance_id': user['instance']}, instance)
        config = {'username': user['email'], 'instance': user['instance'],
                  'fullname': user['fullname'],
                  'server': server, 'password': user['password'],
                  'trust_zones': user['trust_zones'],
                  'gateways': user['gateways'] if 'gateways' in user else [],
                  'Nodes': instance['registered_nodes'] if is_admin else [],
                  'users': instance['users'] if is_admin else []
                 }

        return config

    def determine_server(self, gateway):
        '''
        THis function works in conjunction  with the pinger program.
        the pinger monitors all instances of nodewire servers and helps maintains a list of available servers.
        this function selects from that list.
        :param gateway:
        :return:
        '''
        live_gateway = self.data.live_gateways.find_one({'instance': gateway})
        if not live_gateway:
            self.data.live_gateways.insert({'instance': gateway, 'count': 0})
        if live_gateway and live_gateway['count']!=0: # chose same server as fellow gateways, if a gateway is already connected
            instance = self.data.instances.find_one({'instance_id': gateway})
            d_instance = self.data.servers.find({'ip': instance['config']['cp_address']})
            if d_instance.count()!=0:
                return instance['config']['cp_address']

        if self.data.servers.find_one({'ip': connectedip()}):
            return connectedip() # otherwise, we are free to chose the current server if one exists
        else:
            servers = self.data.servers.find({'public': True}) # else chose any available server
            if servers.count() != 0 :
                n = int(random.random()*servers.count())
                return servers[n]['ip']
            else:
                raise Exception('No server found')

    def create_app(self, owner, layout, title = 'New Layout', target='re',script = [], sketch = [], icon = ''):
        app = {
            'icon': icon,
            'layout': layout,
            'title': title,
            'target': target,
            'script': script,
            'sketch': sketch
        }
        lid = self.data.apps.insert_one(app)
        user = self.data.users.find_one({'email': owner})
        user['apps'].append(str(lid.inserted_id))
        self.data.users.update({'email': owner}, user)
        return str(lid.inserted_id)

    def get_apps(self, owner):
        user = self.data.users.find_one({'email': owner})
        apps = []
        for lo in user['apps']:
            try:
                app = self.data.apps.find_one({'_id': ObjectId(lo)})
                apps.append({'id': str(app['_id']), 'title': app['title']})
            except:
                user['apps'].remove(lo)
                self.data.users.update({'email': owner}, user)
        return apps

    def deploy_app(self, email, app_id):
        app = self.data.apps.find_one({'_id': ObjectId(app_id)})
        user = self.data.users.find_one({'email': email})
        sapp = self.data.store.find_one({'app_id': app_id})
        if sapp or app_id in user['apps']:
            user['layout'] = app['layout'][0]['content']
            user['layout_format'] = 'xml' if app['layout'][0]['name'].endswith('.xml') else 'json'
            pages = []
            for layout in app['layout']:
                pages.append(layout)
            user['pages'] = pages
            self.data.users.update({'email': email}, user)
            return app

    def publish_app(self, email, app_id, tags):
        app = self.data.store.find_one({'app_id': app_id})
        if not app:
            app = {
                'app_id': app_id,
                'app_name': self.data.apps.find_one({'_id': ObjectId(app_id)})['title'],
                'no_installs': 0,
                'rating': 0,
                'published_by': email,
                'tags': tags
            }
            self.data.store.insert_one(app)

    def unpublish_app(self, email, app_id):
        self.data.store.remove({'published_by': email, 'app_id': app_id})

    def get_store_apps(self):
        apps = list(self.data.store.find())
        dapps = []
        for app in apps:
            app['_id'] = str(app['_id'])
            dapps.append(app)
        return dapps



    def open_app(self, email, app_id):
        app = self.data.apps.find_one({'_id': ObjectId(app_id)})
        user = self.data.users.find_one({'email': email})
        if app_id in user['apps']:
            user['layout'] = app['layout'][0]
            self.data.users.update({'_id': email}, user)
            return app['layout']

    def get_page(self, email, page_name):
        user = self.data.users.find_one({'email': email})
        for page in user['pages']:
            if page['name']==page_name:
                return page
        return {}

    def get_pages(self, email):
        user = self.data.users.find_one({'email': email})
        if 'pages' in user:
            return user['pages']
        else:
            return []

    def save_app(self, owner, appid, layout, title = 'New Layout', target='re', script = [], sketch = [], icon = ''):
        user = self.data.users.find_one({'email': owner})
        if appid in user['apps']:
            app = {
                'icon': icon,
                'layout': layout,
                'title': title,
                'target': target,
                'script': script,
                'sketch': sketch
            }
            self.data.apps.update({'_id': ObjectId(appid)}, app)

    def edit_app(self, email, app_id):
        app = self.data.apps.find_one({'_id': ObjectId(app_id)}, {'_id':0})
        user = self.data.users.find_one({'email': email})
        sapp = self.data.store.find_one({'app_id': app_id})
        if sapp:  # if app is published, then it is available to everyone
            return app
        elif app_id in user['apps']:
            return app

    def edit_app_by_name(self, email, app_name):
        app = self.data.apps.find_one({'title': app_name})
        if app:
            user = self.data.users.find_one({'email': email})
            sapp = self.data.store.find_one({'app_id': str(app['_id'])})
            if sapp:  # if app is published, then it is available to everyone
                del app['_id']
                return app
            elif str(app['_id']) in user['apps']:
                del app['_id']
                return app
        return None

    def rename_app(self, email, app_id, new_name):
        app = self.data.apps.find_one({'_id': ObjectId(app_id)}, {'_id':0})
        user = self.data.users.find_one({'email': email})
        if app_id in user['apps']:
            app['title'] = new_name
            self.data.apps.update({'_id': ObjectId(app_id)}, app)

    def delete_app(self, email, app_id):
        user = self.data.users.find_one({'email': email})
        if app_id in user['apps']:
            self.data.apps.remove({'_id': ObjectId(app_id)})
            self.data.store.remove({'email': email, 'app_id': app_id}) # unpublish
            user['apps'].remove(app_id)
            self.data.users.update({'email': email}, user)

if __name__ == '__main__':
    data = Admin()
    data.get_user('stee@mail.com')