# -*- coding: utf-8 -*-
import sys, os, logging, re, time, traceback, codecs
from collections import defaultdict, OrderedDict
from datetime import datetime, timedelta
from decimal import Decimal
from shutil import copyfile
from copy import deepcopy
import tables as tb
import numpy as np
import django
from channels import Channel


from ebest.xingAPI import Session, XAEvents, Query, Real
from ebest.meta import TR, Helper
#from trader.util import util
#from db_manager.manager import Factory
from model import DateMapper, Minute, Daily


BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..\\..\\data')

class Manager:
    """
    데이터 수집 및 갱신하는 클래스
    설명:
        - xing api를 이용해 시장정보 및 거래정보를 수집
        - 종목정보 수집 -> 검증 -> DB에 저장
        - 일간 데이터, 분 데이터 수집
        - 액티브 월물 채택 기준: 근월물과 차월물 중 3 거래일 연속 거래량이 더 큰 월물 채택
    """

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger()
        self.session = Session(self, demo=True)

    #채널에 응답하는 매소드
    def reply(self, method, data, nextwork=None, name="web"):
        Channel(name).send({
            "worker": "manager",
            "method": method,
            "data": data,
            "auto": self.auto
        })

    def backup(self):
        src = os.path.join(BASE_DIR, 'market.hdf5')
        dst_file = 'market_'+datetime.today().strftime('%Y%m%d%H%M%S')+'.hdf5'
        dst = os.path.join(BASE_DIR, dst_file)
        copyfile(src, dst)
        self.logger.info("file has backed up to %s",dst_file)

    def task(self, todo, **args):
        """ 
        task manager
        todo : 'marketinfo' or 'rawdata'
        args:{ 
            key: 로그인키,
            timeframe: 'day' or 'minute',
            activeinfo: 액티브월물 정보
        }
        """

        self.auto = args['auto']
        if 'key' in args: 
            self.key = args['key']

        if todo == 'backup':
            self.backup()

        elif self.session.is_connected():
            #날짜
            self.today = datetime.today().strftime('%Y%m%d')
            self.yesterday = (datetime.today() - timedelta(1)).strftime('%Y%m%d')
            self.timer = time.time() #조회 제한 용 타이머

            # 시장정보 업데이트
            if todo == "marketinfo":
                self.request_marketinfo()

            elif todo == "rawdata":
                #open DB
                db_dir = os.path.join(BASE_DIR, 'market.hdf5')
                filters = tb.Filters(complib='blosc', complevel=9)
                self.h5file = tb.open_file(db_dir, mode="a", filters=filters)
                self.activeinfo = args['activeinfo']

                if args['timeframe'] == 'day':
                    self.request_rawdata('day')
                if args['timeframe'] == 'minute':
                    self.request_rawdata('minute')

        else:
            self.todo = todo
            self.args = args
            self.login(self.key)
    
    def flush(self):
        del self.today
        del self.yesterday
        del self.timer
        if hasattr(self, 'args'): del self.args
        if hasattr(self, 'todo'): del self.todo
        if hasattr(self, 'h5file'): del self.h5file
        if hasattr(self, 'activeinfo'): del self.activeinfo
        if hasattr(self, 'codelength'): del self.codelength
        if hasattr(self, 'products'): del self.products
        if hasattr(self, 'codespair'): del self.codespair
        if hasattr(self, 'cursor'): del self.cursor
        if hasattr(self, 'message'): del self.message
        if hasattr(self, 'lastday'): del self.lastday
        if hasattr(self, 'fields'): del self.fields
        if hasattr(self, 'activeinfo_res'): del self.activeinfo_res
    

    ######################################################################
    ##                         로그인                                   ##
    ######################################################################
    def login(self, key):
        """ 로그인 """
        fdir = os.path.join(BASE_DIR, 'dump')
        with open(fdir, 'r') as f:
            #s = f.read()
            a = f.read().split('\\')
            i = Helper.decrypt(key, codecs.decode(a[0], "hex")).decode("utf-8")
            p = Helper.decrypt(key, codecs.decode(a[1], "hex")).decode("utf-8")

        if self.session.connect_server():
            if self.session.login(i, p):
                self.logger.info("로그인 시도")

        else:
            err = self.session.get_last_error()
            errmsg = self.session.get_error_message(err)
            self.logger.info('Error message: %s', errmsg)

    def parse_err_code(self, trcode, errcode):
        ret = self.session.get_error_message(errcode)
        msg = '({}) {}'.format(trcode, ret)
        self.logger.warning(msg)

    @XAEvents.on('OnLogin')
    def __login(self, code, msg):
        self.logger.info("(%s): %s", code, msg)
        self.task(self.todo, **self.args)

    @XAEvents.on('OnReceiveMessage')
    def _msg_receiver(self, syserr, code, msg):
        if syserr: #True면 시스템 오류
            self.logger.warning("OnReceiveMessage: System Error : (%s) %s", code, msg)
        else:
            self.logger.debug("OnReceiveMessage: (%s) %s", code, msg)


    ######################################################################
    ##                         market-info update                       ##
    ######################################################################
    #1. 전체 종목 정보를 요청
    def request_marketinfo(self):
        self.logger.info("start updating market information")
        tr = TR.o3101
        self.query = Query(self, tr.CODE)
        fields = dict(gubun='')

        errcode = self.query.request(tr.INBLOCK, fields)
        if errcode < 0:
            self.parse_err_code(tr.CODE, errcode)

    #2. 종목 리스트를 정리
    @XAEvents.on('OnReceiveData', code='o3101')
    def __marketinfo(self, code):
        self.products = dict()
        outblock = TR.o3101.OUTBLOCK
        cnt = self.query.get_block_count(outblock)
        for i in range(cnt):
            market = self.query.get_field_data(outblock, 'GdsCd', i) #시장구분
            market = Helper.market_symbol(market)
            group = self.query.get_field_data(outblock, 'BscGdsCd', i) #상품코드
            code = self.query.get_field_data(outblock, 'Symbol', i) #종목코드
            codename = self.query.get_field_data(outblock, 'SymbolNm', i) #종목명
            name = self.query.get_field_data(outblock, 'BscGdsNm', i) #기초 상품명
            month = datetime(
                int(self.query.get_field_data(outblock, 'LstngYr', i)),
                int(Helper.get_month(self.query.get_field_data(outblock, 'LstngM', i))),
                1
            ) #월물

            # 마이크로 상품, 거래량 적은 상품 제외
            if ('micro' in name.lower())\
                or ('mini' in name.lower())\
                or ('miny' in name.lower())\
                or ('vix' in name.lower())\
                or ('mp' in group.lower())\
                or ('suc' in group.lower())\
                or ('hchh' in group.lower())\
                or ('sch' in group.lower())\
                or ('sku' in group.lower())\
                or ('cfi' in group.lower())\
                or ('cer' in group.lower()):
                continue

            if group not in self.products.keys():
                self.products[group] = dict(
                    codes=[], #월물 리스트
                    market=market, #시장구분
                    group=group, #상품구분
                    name=name, #상품명
                    currency=self.query.get_field_data(outblock, 'CrncyCd', i), #통화구분
                    notation=self.query.get_field_data(outblock, 'NotaCd', i), #진법구분
                    tick_unit=float(self.query.get_field_data(outblock, 'UntPrc', i)), #틱 단위
                    tick_value=float(self.query.get_field_data(outblock, 'MnChgAmt', i)), #틱 가치
                    rgl_factor=self.query.get_field_data(outblock, 'RgltFctr', i), #가격 조정계수
                    open_time=self.query.get_field_data(outblock, 'DlStrtTm', i), #거래시작시간
                    close_time=self.query.get_field_data(outblock, 'DlEndTm', i), #거래종료시간
                    is_tradable=self.query.get_field_data(outblock, 'DlPsblCd', i), #거래가능구분
                    open_margin=self.query.get_field_data(outblock, 'OpngMgn', i), #개시증거금
                    keep_margin=self.query.get_field_data(outblock, 'MntncMgn', i), #유지증거금
                    decimal_places=int(self.query.get_field_data(outblock, 'DotGb', i)), #유효소숫점자리수
                    last_update=datetime.now().strftime('%Y%m%d%H%M') #마지막 업데이트
                )

            # 종목별 정리
            self.products[group]['codes'].append(dict(
                group=group,
                code=code,
                codename=codename,
                month=month, #월물
                ec_price=float(self.query.get_field_data(outblock, 'EcPrc', i)), #정산가격
            ))

        self.set_front_month()


    def set_front_month(self):
        """ 근월물과 차월물 선택 매소드 """
        self.codespair = []
        for group in self.products.values():
            codes = group.get('codes')

            if len(codes) == 1:
                group['front'] = codes[0]['code']
                group['active'] = codes[0]['code']
                group['activated_date'] = self.yesterday

            elif len(codes) > 1:
                cm_list = []
                for code in codes:
                    cm_list.append((code['month'], code))
                front_cm = sorted(cm_list)[:2]
                group['front'] = front_cm[0][1]['code']
                group['front_codes'] = (front_cm[0][1], front_cm[1][1])
                self.codespair += [front_cm[0][1], front_cm[1][1]]

        #테스트코드
        #self.codespair = self.codespair[:2]

        self.codeslen = len(self.codespair)
        self.get_volume()

    #3. 일별 거래량 수집
    def get_volume(self):
        tr = TR.o3104 #해외선물 일별
        self.query = Query(self, tr.CODE)
        self.code = self.codespair.pop()
        self.code['volume'] = []
        fields = dict(
            gubun=0, #일별
            shcode=self.code['code'], #종목코드
            date=self.yesterday #어제 날짜 기준
        )

        #조회요청
        errcode = self.query.request(tr.INBLOCK, fields)
        if errcode < 0:
            self.parse_err_code(tr.CODE, errcode)

    @XAEvents.on('OnReceiveData', code='o3104')
    def __get_volume(self, code):
        tr = TR.o3104
        cnt = self.query.get_block_count(tr.OUTBLOCK)

        # 최근 30일치 거래량 수집
        for i in range(10):
            date = self.query.get_field_data(tr.OUTBLOCK, 'chedate', i)
            date = datetime.strptime(date, '%Y%m%d')
            vol = int(self.query.get_field_data(tr.OUTBLOCK, 'volume', i))
            price = float(self.query.get_field_data(tr.OUTBLOCK, 'price', i) or 0)
            self.code['volume'].append((date, vol, price))

        count = self.query.get_tr_count_request(tr.CODE)
        # 10분당 조회 tr 200회 제한
        if count >= 199:
            delta = 60*10 - (time.time() - self.timer)+5
            msg = "need to sleep %s sec"%delta
            self.logger.info(msg)
            self.reply("log", msg)
            time.sleep(delta)
            self.timer = time.time()

        # 로깅
        msg = "Receiving: %s (%s/%s)"%\
              (self.code['codename'], len(self.codespair)+1, self.codeslen)
        self.logger.info(msg)
        self.reply("log", msg)

        if self.codespair:
            time.sleep(tr.TR_PER_SEC+0.1) #조회 제한
            self.get_volume()
        else:
            msg = "*** Market information successfully downloaded ***"
            self.logger.info(msg)
            self.reply("log", msg)

            self.compare_volume()

    #5. 거래량 비교
    def compare_volume(self):
        for group in self.products.values():

            if 'front_codes' in group:
                
                first = group['front_codes'][0]
                second = group['front_codes'][1]
                
                if 'volume' in first and 'volume' in second:
                    group['active'] = group['front']
                    group['activated_date'] = self.yesterday

                    # 거래량 리스트의 길이를 맞춤
                    length = min(len(first['volume']), len(second['volume']))
                    cnt = 0
                    # 차월물의 거래량이 2일 연속 많으면 액티브월물 = 차월물
                    for i in range(length, 0, -1):
                        if first['volume'][i-1][1] < second['volume'][i-1][1]:
                            cnt += 1
                        if cnt == 2:
                            group['active'] = second['code']
                            group['activated_date'] = second['volume'][i-1][0].strftime("%Y%m%d")

                    del first['volume']
                    del second['volume']

                else:
                    msg = "volume of %s for comparison does not exist"%group['name']
                    self.logger.info(msg)
                    self.reply("log", msg)

        self.pass_to_django()

    #6. django로 넘기기
    def pass_to_django(self):
        for group in self.products.values():
            for code in group['codes']:
                code['month'] = code['month'].strftime("%Y%m")

        self.reply("marketinfo", self.products, name="post-work")
        self.flush()


    ######################################################################
    ##                         Daily OHLC Update                        ##
    ######################################################################
    def request_rawdata(self, work):
        """
        데이터 받기 세팅
        db에 저장된 최신 데이터의 액티브 월물이 현재 액티브월물과 다른경우
        액티브 월물의 갱신 날짜까지는 과거 종목으로 데이터를 받고
        갱신 날짜 다음날 부터 갱신된 액티브 월물 데이터를 받는다.
        """
        self.message = [] #월물 업데이트 정보
        self.activeinfo_res = deepcopy(self.activeinfo)
        # 신규 종목 db 생성
        for product in self.activeinfo:
            if not hasattr(self.h5file.root, product['group']):
                node = self.h5file.create_group('/', product['group'] , product['name'])
                ohlc = self.h5file.create_table(node, "Daily", Daily, "Daily Raw Data")
                ohlc.cols.date.create_csindex()
                self.h5file.create_table(node, "Minute", Minute, "Minutely Raw Data")
                self.h5file.create_table(node, "DateMapper", DateMapper, "date array for Minute")
                self.h5file.flush()

        self.codelength = len(self.activeinfo)
        if work == 'day':
            self.get_daily_data()
        if work == 'minute':
            self.get_minute_data()

    def get_daily_data(self):
        #tr 정보
        tr = TR.o3108
        self.query = Query(self, tr.CODE)

        #db 정보
        self.active = self.activeinfo.pop()
        grp = self.active['group']
        self.cursor = getattr(self.h5file.root, grp).Daily #db 커서
        self.lastday = max(self.cursor.cols.date, default=np.array(0)) #최근 저장된 날짜
        startday = ''.join(str(self.lastday.astype('M8[s]').astype('M8[D]')
                               + np.timedelta64(1)).split('-')) #시작일
        # db에 액티브월물 저장 안되어있으면 저장하기
        if not hasattr(self.cursor.attrs, 'active'):
            self.cursor.attrs.active = self.active['active']

        active = self.cursor.attrs.active #db에 저장된 종목 코드

        # 액티브 월물이 변경된 경우: 선 갭보정 후 다운
        if self.active['active'] != active:
            #digit = self.active['decimal_places'] #소숫점자릿수(반올림용)
            price_gap = self.active['price_gap']
            self.cursor.cols.open[:] = self.cursor.cols.open[:] + price_gap
            self.cursor.cols.high[:] = self.cursor.cols.high[:] + price_gap
            self.cursor.cols.low[:] = self.cursor.cols.low[:] + price_gap
            self.cursor.cols.close[:] = self.cursor.cols.close[:] + price_gap
            self.cursor.attrs.active = self.active['active'] # db에 새로운 액티브 코드 저장
            self.cursor.flush()
            self.message.append("!!! %s Data Has been changed up by %s from %s"%\
                             (self.active['name'], price_gap, self.lastday.astype('M8[s]')))

        self.fields = dict(
            shcode=self.active['active'],
            gubun=0, #일별
            qrycnt=500,
            sdate=startday,
            edate=self.yesterday,
            cts_date='',
        )

        # 로깅
        msg = "Starting to get data : %s, last date: %s"\
              %(self.active['name'], self.lastday.astype('M8[s]').astype('M8[D]'))
        self.logger.info(msg)

        #조회 요청
        errcode = self.query.request(tr.INBLOCK, self.fields)
        if errcode < 0:
            self.parse_err_code(tr.CODE, errcode)

    @XAEvents.on('OnReceiveData', code='o3108')
    def _on_get_daily_data(self, code):
        tr = TR.o3108
        data = []

        shcode = self.query.get_field_data(tr.OUTBLOCK, 'shcode', 0) #종목코드
        cts_date = self.query.get_field_data(tr.OUTBLOCK, 'cts_date', 0) #연속일자

        cnt = self.query.get_block_count(tr.OUTBLOCK1)
        for i in range(cnt):
            date = self.query.get_field_data(tr.OUTBLOCK1, 'date', i) #날짜
            open = self.query.get_field_data(tr.OUTBLOCK1, 'open', i) #시가
            high = self.query.get_field_data(tr.OUTBLOCK1, 'high', i) #고가
            low = self.query.get_field_data(tr.OUTBLOCK1, 'low', i) #저가
            close = self.query.get_field_data(tr.OUTBLOCK1, 'close', i) #종가
            volume = self.query.get_field_data(tr.OUTBLOCK1, 'volume', i) #거래량

            #날짜가 이상할때가 있음.
            try:
                ndate = np.datetime64(datetime.strptime(date, '%Y%m%d')).astype('uint64')/1000000
                sdate = datetime.strptime(date, '%Y%m%d').strftime('%Y-%m-%d')
            except:
                self.logger.warning("%s has a missing DATE or something is wrong", shcode)
                self.logger.error(traceback.format_exc())
                continue

            #거래량이 1  미만이면 버림
            if int(volume) < 1:
                self.logger.info("%s with volume %s will be passed at %s", shcode, volume, date)
                continue

            if np.rint(ndate) <= np.rint(self.lastday):
                self.logger.warning("Last date of %s in DB matched at %s", shcode, date)
                continue

            if self.cursor.read_where('date==ndate').size:
                self.logger.info("duplicated date: %s", sdate)
                continue
            datum = (ndate, open, high, low, close, volume)
            data.append(datum)

        count = self.query.get_tr_count_request(tr.CODE)

        if data:
            msg = "Updating daily: %s at  %s, TR: %s, (%s/%s)"\
                  %(self.active['name'], sdate, count, len(self.activeinfo), self.codelength)
            self.logger.info(msg)
            self.reply("log", msg)
            self.cursor.append(data)
            self.cursor.flush()
        else:
            msg = "Nothing to update: %s , TR: %s, remained=(%s/%s)"\
                  %(self.active['name'], count, len(self.activeinfo), self.codelength)
            self.logger.info(msg)
            self.reply("log", msg)

        # 10분당 조회 tr 200회 제한
        if count >= 199:
            delta = 60*10 - (time.time() - self.timer)+5
            msg = 'need to sleep %s sec'%delta
            self.logger.info(msg)
            self.reply("log", msg)
            time.sleep(delta)
            self.timer = time.time()

        time.sleep(1) #Tr 조회 제한
        if cts_date != '00000000':
            self.fields['cts_date'] = cts_date
            errcode = self.query.request(tr.INBLOCK, self.fields, bnext=True)
            if errcode < 0:
                self.parse_err_code(tr.CODE, errcode)

        else:
            if self.activeinfo:
                self.get_daily_data()
            else:
                for msg in self.message:
                    self.logger.info(msg)
                    self.reply("log", msg)
                msg = "** Daily Data updated completely **"
                self.logger.info(msg)
                self.reply("log", msg)

                if self.auto:
                    self.activeinfo = deepcopy(self.activeinfo_res)
                    self.get_minute_data()
                else:
                    self.h5file.close()
                    self.flush()

    ######################################################################
    ##                         Minute Data Update                       ##
    ######################################################################
    def get_minute_data(self):
        """ 분봉 데이터 받기 """
        #tr 정보
        tr = TR.o3103
        self.query = Query(self, tr.CODE)

        #db 정보
        self.active = self.activeinfo.pop()
        grp = self.active['group']
        
        self.m_cursor = getattr(self.h5file.root, grp).Minute #db 커서
        self.d_cursor = getattr(self.h5file.root, grp).DateMapper
        self.lastdate = max(self.d_cursor.cols.date, default=np.array(0)) #최근 저장된 날짜
        self.flag = False #last date 매칭 되었을때 사용

        if not hasattr(self.m_cursor.attrs, 'active'):
            self.m_cursor.attrs.active = self.active['active']
        
        active = self.m_cursor.attrs.active #db에 저장된 종목 코드

        # 액티브 월물이 변경된 경우: 선 갭보정 후 다운
        if self.active['active'] != active:
            price_gap = self.active['price_gap'] #가격 차이
            #데이터 변환
            self.m_cursor.cols.price[:] = self.m_cursor.cols.price[:] + price_gap
            self.m_cursor.attrs.active = self.active['active'] #새로운 액티브 코드 저장
            self.m_cursor.flush()
            self.message.append("!!!CASE1: %s Data Has been changed up by %s from %s"%\
                             (self.active['name'], price_gap, self.lastdate.astype('M8[s]')))

        self.fields = dict(
            shcode=self.active['active'],
            ncnt=1, #분단위
            readcnt=500,
            cts_date='',
            cts_time='',
        )

        # 로깅
        self.logger.info("Started to get MINUTE data : %s upto %s",
                         self.active['name'], self.lastdate.astype('M8[s]'))

        # 조회 요청
        errcode = self.query.request(tr.INBLOCK, self.fields)
        if errcode < 0:
            self.parse_err_code(tr.CODE, errcode)

    @XAEvents.on('OnReceiveData', code='o3103')
    def _on_get_minute_data(self, code):
        tr = TR.o3103

        shcode = self.query.get_field_data(tr.OUTBLOCK, 'shcode', 0) #종목코드
        cts_date = self.query.get_field_data(tr.OUTBLOCK, 'cts_date', 0) #연속일자
        cts_time = self.query.get_field_data(tr.OUTBLOCK, 'cts_time', 0) #연속시간
        timediff = int(self.query.get_field_data(tr.OUTBLOCK, 'timediff', 0)) * (-1) #시차

        cnt = self.query.get_block_count(tr.OUTBLOCK1)
        for i in range(cnt):
            date = self.query.get_field_data(tr.OUTBLOCK1, 'date', i) #날짜
            dtime = self.query.get_field_data(tr.OUTBLOCK1, 'time', i) #시간
            high = float(self.query.get_field_data(tr.OUTBLOCK1, 'high', i)) #고가
            low = float(self.query.get_field_data(tr.OUTBLOCK1, 'low', i)) #저가
            volume = int(self.query.get_field_data(tr.OUTBLOCK1, 'volume', i)) #거래량

            items = []
            dates = []

            #날짜가 이상할때가 있음.
            try:
                ndate = np.datetime64(datetime.strptime(date+dtime, '%Y%m%d%H%M%S')) \
                         + np.timedelta64(timediff, 'h')
                ndate = ndate.astype('uint64')/1000000
                sdate = datetime.strptime(date+dtime, '%Y%m%d%H%M%S') + timedelta(hours=timediff)
                sdate = sdate.strftime('%Y-%m-%dT%H:%M:%S')
            except:
                self.logger.warning("%s has a missing DATE or something is wrong %s,%s", shcode, date, dtime)
                self.logger.error(traceback.format_exc())
                continue


            #거래량이 1 미만이면 버림
            if int(volume) < 1:
                self.logger.info("%s with volume %s will be passed at %s", shcode, volume, sdate)
                continue

            #db에 저장된 최근 날짜보다 이전이면 끝냄
            if np.rint(ndate) <= np.rint(self.lastdate):
                self.flag = True
                self.logger.warning("Last date of %s in DB matched at %s", shcode, sdate)
                break

            # 날짜 겹치면 버림
            if self.d_cursor.read_where('date==ndate').size:
                self.logger.info("duplicated date: %s", sdate)
                continue

            else:
                idx = self.d_cursor.cols.mapper[-1] + 1 #매핑 인덱스
                mapper = (ndate, idx)
                dates.append(mapper)
                digit = self.active['decimal_places']
                tickunit = self.active['tick_unit']
                
                if round(low, digit) == round(high, digit):
                    item = (idx, round(low, digit), volume)
                    items.append(item)

                else:
                    length = (high-low)/tickunit + 1
                    length = np.rint(length)
                    value = volume/length

                    if np.isinf(value) or (value < 0.1): #inf value 종종 생겨서..
                        self.logger.warning("wrong volume: %s, length: %s at %s",
                                            volume, length, sdate)
                        continue

                    for price in np.arange(round(low, digit), high - tickunit/2, tickunit):
                        item = (idx, round(price, digit), value)
                        items.append(item)

                if items:
                    self.d_cursor.append(dates)
                    self.m_cursor.append(items)
                    self.d_cursor.flush()
                    self.m_cursor.flush()

        count = self.query.get_tr_count_request(tr.CODE)

        if 'items' in locals() and items:
            msg = "Updating Minute data: %s, TR: %s, remained=(%s/%s)"\
                  %(self.active['name'], count, len(self.activeinfo), self.codelength)
            self.logger.info(msg)
            self.reply("log", msg)
        else:
            msg = "Nothing to update: %s, TR: %s, remained=(%s/%s)"\
                 %(self.active['name'], count, len(self.activeinfo), self.codelength)
            self.logger.info(msg)
            self.reply("log", msg)

        # 10분당 조회 tr 200회 제한
        if count >= 199:
            delta = 60*10 - (time.time() - self.timer)+5
            msg = "need to sleep %s sec"%delta
            self.logger.info(msg)
            self.reply("log", msg)
            time.sleep(delta)
            self.timer = time.time()

        time.sleep(tr.TR_PER_SEC+0.1) #Tr 조회 제한
        if (cts_date == '00000000') or self.flag:
            if 'sdate' in locals():
                self.logger.info("Reached last date at  %s", sdate)

            if self.activeinfo:
                self.get_minute_data()
            else:
                for msg in self.message:
                    self.logger.info(msg)
                    self.reply("log", msg)
                msg = "** Minute Data updated completely **"
                self.logger.info(msg)
                self.reply("log", msg)
                self.h5file.close()
                self.flush()
                #자동 백업
                if self.auto:
                    self.backup()

        elif cts_date != '00000000':
            self.fields['cts_date'] = cts_date
            self.fields['cts_time'] = cts_time
            errcode = self.query.request(tr.INBLOCK, self.fields, bnext=True)
            if errcode < 0:
                self.parse_err_code(tr.CODE, errcode)

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    app = QApplication(sys.argv)
    update = Update()
    update.login()
    sys.exit(app.exec_())