from django.views.generic.base import TemplateView
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.shortcuts import render
from django.http import JsonResponse
#from channels import Channel

from trading.models import Product

decorators = [login_required, ensure_csrf_cookie]

@method_decorator(decorators, name='dispatch')
class MarketView(TemplateView):
    template_name = 'marketapp/market.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['markets'] = list(set(Product.objects.all().values_list("market", flat=True)))
        return context
