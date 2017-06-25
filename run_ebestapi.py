import sys
import os
import logging
import time

from carpediem.asgi import channel_layer

import pythoncom

from ebest.app import eBest
#from xingapi.meta import TR, Helper

# web에서 보낸 message를 파싱하여 해당하는 action을 진행 하는 main controller
def main():

    ebest = eBest()
    ebest.login()



    while True:
        #channel_layer.send("background-hello",{"text": "Test from the external: " + str(randint(0,100000))})
        #channel_layer.send_group(Channel('background-hello'), 
        #  {"text":"Test from the external: " + str(randint(0,100000))})
        pythoncom.PumpWaitingMessages()
        s = channel_layer.receive(["test"], block=False)
        if s[0]:
            logging.info(s)
        time.sleep(0.1)


if __name__ == '__main__':
    logging.basicConfig(format="[%(levelname)s] %(message)s", level=logging.DEBUG)
    #logging.getLogger().addHandler(logging.StreamHandler())
    logging.info("program started")
    main()