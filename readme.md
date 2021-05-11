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
- Rapid development of software that uses connected hardware for quick prototyping and eventual deployment.
- Write software that talk to one another, like microservices
- Can be hosted on small devices, e.g microcontrollers
- Nodes can be reached via plaintalk, mqtt or REST
- Nodes can talk to other Nodes as well as to an integrated mongodb database
- Nodes are managed. Permissions. Access control. Dashboard.

Use Cases
------------
**Serverless web App.**

Python Node + Javascript client

A static website with embedded javascript plus a python node which serves as the server. The python node will have inputs and outputs ports that maps to REST functions which can be called by a javascript client. Alternatively, the javascript client can use plaintalk to define its own nodes which can then be dynamically wired by using a sketch defined in the rule engine.

**API**

server is a node written in python, javascript or C++ and can be hosted anywhere from a software module to a browser session to a microcontroller. The NodeWire server automatically creates REST endpoints for each connected Node, exposing each port as an individual endpoint.

**IoT device**

Machine to machine, machine to software or software to software communication using MQTT, PlainTalk or REST.



Repositories
------------------
- Plaintalk: Persistent Connection, queue, plaintalk
  - python
  - cpp
  - javascript
  - c# 
- NodeWire Client: 
  - python and micropython
  - c++ and arduino
  - javascript and reactjs
  - c# and dotnetcore
- NodeWire Server: cp, ee, db, mqtt, rest
- NodeWire Develop: dashboard, scripting, graphs, sketch
- Documentation
