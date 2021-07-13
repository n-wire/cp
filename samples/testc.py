from nodewire.control import control
import os


class bright(object):
    def on_brightness(self, Sender, Value):
        pass

    async def get_count(self, Sender):
        return 101

    async def on_volume(self, Sender, Value):
        print(Value)

if __name__ == '__main__':
    ctrl = control(inputs = 'brightness volume', outputs = 'count', handler=bright(), server='localhost')
    ctrl.nw.debug = True
    ctrl.nw.run()