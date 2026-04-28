from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0013_post_ip_address_postinteraction_ip_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="tagged_user_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="postinteraction",
            name="attachments",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="postinteraction",
            name="link_url",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="postinteraction",
            name="tagged_user_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
