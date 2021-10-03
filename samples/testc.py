from nodewire import Node
import os


class bright(Node):
    def on_brightness(self, Sender, Value):
        pass

    async def get_count(self, Sender):
        return 101

    async def on_volume(self, Sender, Value):
        print(Value)

if __name__ == '__main__':
    ctrl = bright(inputs = 'brightness volume', outputs = 'count', server='localhost')
    ctrl.nw.debug = True
    ctrl.nw.run()