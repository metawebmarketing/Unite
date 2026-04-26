from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ads", "0002_addeliveryevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="adslotconfig",
            name="account_tier_target",
            field=models.CharField(
                choices=[("any", "Any"), ("human", "Human only"), ("ai", "AI only")],
                default="any",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="adslotconfig",
            name="campaign_key",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="adslotconfig",
            name="experiment_key",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="adslotconfig",
            name="target_interest_tags",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
