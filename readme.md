NodeWire 2.0
=============
What is NodeWire?
-----------------
A Reactive, dataflow, concurrency, event/message-driven programming framework, analogous to an electronic (digital) circuit.
Each component is a node.

Node = I/O Ports + FSM

Node is a software module. It can be inside a device such as sensors. It is the abstraction of a connected IoT device. Nodes send messages to each other (dataflow) via the NodeWire server, aka command processor (cp). A special component of the cp is the rule engine, which is used to define loosely coupled connections (wires) between nodes. A node is said to be wired to another node if one or more of it's inputs is a function of the output(s) of the other node. For example, a power generator can be started by a battery low message from an inverter. The interconnect is defined by a sketch which is either a graphical design file (circuit) or a script. The sketch is itself a Node.

The inside of a Node is essentially a finite state machine (FSM) and can be written in the software tools available on the target platform.

Aims of NodeWire
-------------------
- Rapid development of software that uses connected hardware for quick prototyping and deployment.
- Write software that talk to one another, like microservices
- Can be hosted on small devices, e.g microcontrollers
- Nodes can speak plaintalk, mqtt or REST
- Nodes can talk to other Nodes as well as to an integrated mongodb database
- Nodes are managed. Permissions. Access control. Dashboard.


Running
--------

```bash
cd cp
python cp
```


Contributing
----------
Whether reporting bugs, discussing improvements and new ideas or writing extensions: Contributions to NodeWire are welcome! Here's how to get started:

1. Check for open issues or open a fresh issue to start a discussion around a feature idea or a bug
2. Fork the repository on Github, create a new branch off the master branch and start making your changes (known as GitHub Flow)
3. Write a test which shows that the bug was fixed or that the feature works as expected
4. Send a pull request and bug the maintainer until it gets merged and published 

See https://hub.github.com/ to learn how to fork and submit pull requests


dependencies
--------
 
- pyjwt
- sanic
- hbmqtt


devops
---------
https://deepsource.io/python-static-code-analysis/
