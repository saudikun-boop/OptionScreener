from ib_insync import IB

ib = IB()
ib.connect('127.0.0.1', 4001, clientId=1)

print(f"Connected: {ib.isConnected()}")
print(f"Server version: {ib.client.serverVersion()}")

ib.disconnect()
