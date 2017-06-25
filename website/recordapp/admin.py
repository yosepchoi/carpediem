from django.contrib import admin
from .models import Product, Code, Entry, Game, Account, Exit
# Register your models here.

admin.site.register([Product, Code, Entry, Game, Account, Exit])
