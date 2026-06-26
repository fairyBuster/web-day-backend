from django import template

register = template.Library()

@register.filter(name="format_currency")
def format_currency_filter(value):
    from config import format_currency

    return format_currency(value)

@register.filter(name='get_item')
def get_item(dictionary, key):
    return dictionary.get(key, 0)

@register.filter(name='to_items')
def to_items(value):
    if isinstance(value, dict):
        return sorted(value.items())
    return []
