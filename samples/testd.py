import paho.mqtt.client as mqtt #import the client1
import time

the_instance = 'hx3f3tc8zct7'
the_node = "counter"
username = "ahmad.s@faxter.com"
password = "aB01@"

def on_message(client, userdata, message):
    global count
    print("message received " ,str(message.payload.decode("utf-8")))
    print("message topic=",message.topic)
    if message.topic == f'{the_instance}/{the_node}/reset/set': # receive new value for input port
        count = int(message.payload.decode("utf-8"))
        print(count)
        client.publish(f"{the_instance}/{the_node}/count", message.payload)

def on_connect(mqttc, obj, flags, rc):
    print("connected: " + str(rc))
    # client.publish("nodewire/instances", the_instance)  # the instance
    # client.publish(f"{the_instance}/nodes", the_node)       # the node name
    client.publish(f"{the_instance}/{the_node}/count", "0")     # output port
    client.subscribe(f"{the_instance}/{the_node}/reset/set")    # input port
    client.publish(f"{the_instance}/{the_node}/reset", 0)     # input port

def on_disconnect(client, obj, rc):
    print('disconnected')
    client.user_data_set(obj + 1)
    #if obj == 0:
    time.sleep(5)
    print('reconnecting')
    client.reconnect()

broker_address = "localhost" # our broker address
print("creating new instance")
client = mqtt.Client('counter')  # create new instance
client.on_message=on_message  # attach function to callback
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.user_data_set(0)
print("connecting to broker")
client.username_pw_set(username, password=password)
client.connect(broker_address)  # connect to broker
# you can publish and subscribe to topics here but better to do that under the on_connect event

last_time = time.time()
count = 0
while True:
    client.loop()
    if time.time()-last_time>1:
        last_time = time.time()
        count = count + 1
        # print(count)
        client.publish(f"{the_instance}/{the_node}/count", count)
        if count == 10: client.publish(f"{the_instance}/mynode/reset/set", 1)
