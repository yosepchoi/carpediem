from django.db import models
from django.forms import ModelForm
from django import forms
from django.db.models import Sum
from datetime import date

# Create your models here.
class Product(models.Model):
    """ 상품 정보 """
    name = models.CharField(max_length=50, unique=True) # 상품명
    group = models.CharField(primary_key=True, max_length=30, unique=True) #그룹 코드
    market = models.CharField(max_length=10) #시장구분
    active = models.CharField(max_length=10,null=True, blank=True) #액티브 월물명
    front = models.CharField(max_length=10,null=True, blank=True) #근월물명
    activated_date = models.DateField(null=True, blank=True) #액티브 월물 변경일
    price_gap = models.DecimalField(max_digits=20, decimal_places=7, null=True, blank=True) #가격 갭 
    currency = models.CharField(max_length=10) #기준 통화
    open_margin = models.DecimalField(max_digits=10, decimal_places=2)
    keep_margin = models.DecimalField(max_digits=10, decimal_places=2)
    open_time = models.TimeField()
    close_time = models.TimeField()
    tick_unit = models.DecimalField(max_digits=20, decimal_places=7)
    tick_value = models.DecimalField(max_digits=20, decimal_places=3)
    commission = models.DecimalField(max_digits=5, decimal_places=2)
    notation = models.PositiveSmallIntegerField() # 진법
    decimal_places = models.PositiveSmallIntegerField()
    last_update = models.DateTimeField()


    def __str__(self):
        return self.name

class Code(models.Model):
    """ 월물별 상품 정보 """
    code = models.CharField(primary_key=True, max_length=10)
    product = models.ForeignKey('Product', on_delete=models.CASCADE)
    month = models.DateField() #만기월물
    ec_price = models.DecimalField(max_digits=20, decimal_places=7) #정산가격

    def __str__(self):
        return self.code


class Game(models.Model):
    # choices
    POSITION = (
        (1, 'Long'),
        (-1, 'Short')
    )

    #계획
    pub_date = models.DateField(default=date.today)
    product = models.ForeignKey('Product', on_delete=models.PROTECT, null=True, blank=True)
    name = models.CharField(max_length=50, blank=True)
    position = models.IntegerField(choices=POSITION) #포지션

    #결과
    profit = models.DecimalField(null=True, blank=True, max_digits=20, decimal_places=3) #손익
    profit_per_contract = models.DecimalField(null=True, blank=True, max_digits=20, decimal_places=3) #단위손익
    commission = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True) #수수료

    #완료
    is_completed = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.product:
            self.name = self.product.name

        agg = self.exit_set.all().aggregate(
            profit=Sum('profit'),
            commission=Sum('commission'),
            ppc=Sum('profit_per_contract')
            )
        self.profit = agg.get('profit') if agg.get('profit') else 0
        self.profit_per_contract = agg.get('ppc')/self.exit_set.all().count() if agg.get('ppc') else 0
        self.commission = agg.get('commission') if agg.get('commission') else 0
        super(Game, self).save(*args, **kwargs)

    def __str__(self):
        return self.name + " #" + str(self.id)

class Entry(models.Model):
    """ 진입 내역 """
    game = models.ForeignKey('Game', on_delete=models.CASCADE)
    entry_date = models.DateTimeField() #진입날짜
    contracts = models.PositiveSmallIntegerField(default=1) #계약수
    entry_price = models.DecimalField(max_digits=20, decimal_places=7) #진입가격
    loss_cut = models.DecimalField(max_digits=20, decimal_places=7) #로스컷
    plan = models.CharField(max_length=50, null=True, blank=True) #매매전략
    comment = models.CharField(max_length=100, null=True, blank=True) #비고

    def __str__(self):
        return self.game.name+' #'+str(self.id)


class Exit(models.Model):
    """ 청산 내역 """
    game = models.ForeignKey('Game', on_delete=models.CASCADE)
    entry = models.ForeignKey('Entry', on_delete=models.CASCADE)
    exit_date = models.DateTimeField() #청산날짜
    contracts = models.PositiveSmallIntegerField(default=1) #계약수
    exit_price = models.DecimalField(max_digits=20, decimal_places=7) #청산가격

    #단위 결과
    profit = models.DecimalField(blank=True, max_digits=20, decimal_places=3) #손익
    profit_per_contract = models.DecimalField(null=True, blank=True, max_digits=20, decimal_places=3) #단위손익
    commission = models.DecimalField(max_digits=5, decimal_places=2, blank=True) #수수료
    holding_period = models.DurationField(blank=True) #보유기간
    ptr_ratio = models.DecimalField(null=True, blank=True, max_digits=10, decimal_places=2) #ptr ratio

    def save(self, *args, **kwargs):
        # 손익 계산
        if self.game.product:
            product = self.game.product
            price_diff = (self.exit_price - self.entry.entry_price) * self.game.position
            tick_diff = round(price_diff/product.tick_unit)
            risk = round(abs(self.entry.loss_cut - self.entry.entry_price)/product.tick_unit)*product.tick_value
            self.commission = product.commission * self.contracts
            self.profit_per_contract = tick_diff * product.tick_value - product.commission
            self.profit = tick_diff * self.contracts * product.tick_value - self.commission
            self.holding_period = self.exit_date - self.entry.entry_date
            self.ptr_ratio = self.profit_per_contract / risk if risk else 0
        super(Exit, self).save(*args, **kwargs)

    def __str__(self):
        return str(self.id)

class Account(models.Model):
    """
    계좌
    """
    date = models.DateField(null=True, blank=True)
    krw = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    usd = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cash = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return str(self.date)


# Web forms
class GameForm(ModelForm):
    pub_date = forms.DateField(input_formats=['%Y-%m-%d'])
    class Meta:
        model = Game
        fields = [
            'pub_date',
            'name',
            'position',
        ]

class EntryForm(ModelForm):
    entry_date = forms.DateTimeField(input_formats=['%Y-%m-%dT%H:%M'])
    class Meta:
        model = Entry
        fields = [
            'entry_date',
            'entry_price',
            'contracts',
            'loss_cut',
            'plan',
            'comment'
        ]

class ExitForm(ModelForm):
    exit_date = forms.DateTimeField(input_formats=['%Y-%m-%dT%H:%M'])
    class Meta:
        model = Exit
        fields = [
            'exit_date',
            'exit_price',
            'contracts',
        ]
