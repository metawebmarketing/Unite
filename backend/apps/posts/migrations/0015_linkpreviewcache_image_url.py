from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0014_post_tagged_user_ids_postinteraction_attachments_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="linkpreviewcache",
            name="image_url",
            field=models.URLField(blank=True, default=""),
            preserve_default=False,
        ),
    ]
