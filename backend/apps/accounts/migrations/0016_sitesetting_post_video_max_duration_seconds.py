from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_sitesetting_media_storage_and_video_limits"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesetting",
            name="post_video_max_duration_seconds",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
