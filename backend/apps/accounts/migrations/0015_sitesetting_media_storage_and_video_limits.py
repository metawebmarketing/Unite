from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_sitesetting_daily_post_reply_share_limit"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesetting",
            name="media_public_base_url",
            field=models.URLField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="sitesetting",
            name="media_storage_mode",
            field=models.CharField(
                blank=True,
                choices=[("local", "Local"), ("s3", "S3")],
                default="",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="sitesetting",
            name="post_video_max_upload_bytes",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
