from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_sitesetting_user_connection_limit_and_char_cap"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesetting",
            name="daily_post_reply_share_limit",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
