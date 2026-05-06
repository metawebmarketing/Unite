from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_sitesetting_allow_signup_on_ip_country_lookup_failure_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesetting",
            name="post_reply_share_char_cap",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="sitesetting",
            name="user_connection_limit",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
