from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ads", "0003_adslotconfig_targeting_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="addeliveryevent",
            name="campaign_key",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
