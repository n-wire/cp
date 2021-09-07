NodeWire 2.0
=============
What is NodeWire?
-----------------
A Reactive, dataflow, concurrency, event/message-driven framework for building IoT devices and/or microservices, with a programming model that is analogous to an electronic (digital) circuit.

In NodeWire, every component is a node.

Node = I/O Ports + FSM

A Node is a software module. It can be inside a device such as sensors. It is the abstraction of a connected IoT device or software service. Nodes send messages to each other (dataflow) via the NodeWire server, aka command processor (cp). A special component of the cp is the execution engine, which is used to define loosely coupled connections (wires) between nodes. A node is said to be wired to another node if one or more of it's inputs is a function of the output(s) of the other node. For example, a standby generator can be started by a battery low message from an inverter. The interconnect is defined by a sketch which is either a graphical design file (circuit) or a script. The sketch is itself a Node.

The inside of a Node is essentially a finite state machine (FSM) and can be written in the software tools available on the target platform.


Running
--------
Install docker (see: https://docs.docker.com/desktop/windows/install/), then
```
cd cp
docker-compose up -d
```

Open your browser and then enter "localhost:5001" into the address bar

Using NodeWire Cloud
-------------
Instead of installing NodeWire, you can create an account on the cloud service: https://s2.nodewire.org

Getting Started
------------
Create a node in python. On your local computer:

```bash
python -m pip install nodewire
```

type and save,

```python
import asyncio
from nodewire import Node

class MyNode(Node):
    def on_reset(self, value, sender):
        self.count = value

    async def loop(self):
        print('connected')
        while True:
            await asyncio.sleep(1)
            if self.start==1: 
                self.count = self.count + 1

mynode = MyNode(inputs='start reset', outputs='count',  server='localhost')
mynode.nw.run()
```

use server = 'localhost' if you are running nodewire from docker else use 's2.nodewire.org' or remove the parameter altogether. save the file and execute from the command pront:

```bash
python <file_name.py>
```

follow the instructions to register the new node and then go to the dashboard to add the new node by selecting the add menu item (with the + icon). Take note of the name.

Open the nodewire dashboard on your browser and type in the following:

```html
<div>
    <script>
        getNode('pynode')
    </script>
    <div>
        expr:pynode.count
    </div>
    <button onClick="action:pynode.start=1">start</button>
    <button onClick="action:pynode.start=0">stop</button>
    <input change="entered" value="expr:entered" />
    <button onClick="action:pynode.reset=int(entered)">set</button>
</div>
```

Note that you may have to change the node name (pynode) to reflect the name used during the configuration of the python node above.

Tutorials
-------------
- [Creating Nodes on NodeWire Dashboard using HTML and Scripts](https://github.com/n-wire/dashboard)
- [Creating Nodes in Python](https://github.com/n-wire/py_client)
- Creating Nodes in Javascript
- Creating Nodes using Micropython
- Creating Nodes in Arduino
- Creating Nodes in C# and .net


Contributing
----------
Whether reporting bugs, discussing improvements and new ideas or writing extensions: Contributions to NodeWire are welcome! Here's how to get started:

1. Check for open issues or open a fresh issue to start a discussion around a feature idea or a bug
2. Fork the repository on Github, create a new branch off the master branch and start making your changes (known as GitHub Flow)
3. Write a test which shows that the bug was fixed or that the feature works as expected
4. Send a pull request and bug the maintainer until it gets merged and published 