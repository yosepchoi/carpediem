"""carpediem URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.10/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  url(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  url(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.conf.urls import url, include
    2. Add a URL to urlpatterns:  url(r'^blog/', include('blog.urls'))
"""
from django.conf.urls import url, include
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.views.generic.base import RedirectView

from recordapp import views as recordviews
from marketapp import views as marketviews

urlpatterns = [
    # Admin pages
    url(r'^admin/', admin.site.urls, name="admin"),
    #url(r'^$', RedirectView.as_view(pattern_name='overview', permanent=False)),

    # Recordapp pages
    url(r'^$', recordviews.Home.as_view(), name="home"),
    url(r'^records/trading', recordviews.TradingView.as_view(), name="trading"),
    url(r'^records/account', recordviews.InitializeView.as_view(), name="initialize"),

    # Marketapp pages
    url(r'^market/', marketviews.MarketView.as_view(), name="marketview"),

    #Login/Logout URLs
    url(r'^login/$', 
     auth_views.login, {'template_name': 'login.html'}, name='login'),
    url(r'^logout/$',
     auth_views.logout, {'next_page': '/login/'}, name='logout'),
]
