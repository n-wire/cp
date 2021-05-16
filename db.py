import motor.motor_asyncio

nw_server = 'localhost'
# f = open("../datasource", "r")
# w_server = f.readline().strip()
# f.close()

mongo_client = motor.motor_asyncio.AsyncIOMotorClient(nw_server, 27017)