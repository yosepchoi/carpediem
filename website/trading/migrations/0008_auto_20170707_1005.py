# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-07-07 10:05
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trading', '0007_equity_estimated_profit'),
    ]

    operations = [
        migrations.AlterField(
            model_name='entry',
            name='entry_date',
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name='exit',
            name='exit_date',
            field=models.DateField(),
        ),
    ]
