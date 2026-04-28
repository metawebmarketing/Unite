from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0012_post_sentiment_needs_rescore"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="ip_address",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="postinteraction",
            name="ip_address",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
    ]
