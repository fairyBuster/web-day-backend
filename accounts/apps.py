from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        from django.db.models.signals import post_save
        from accounts.models import GeneralSetting
        from config import clear_currency_cache

        post_save.connect(
            lambda **kwargs: clear_currency_cache(),
            sender=GeneralSetting,
            dispatch_uid="accounts.generalsetting.clear_currency_cache",
        )
