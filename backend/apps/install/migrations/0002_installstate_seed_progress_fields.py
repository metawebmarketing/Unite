from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("install", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="installstate",
            name="seed_created_posts",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="installstate",
            name="seed_created_users",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="installstate",
            name="seed_last_message",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="installstate",
            name="seed_total_posts",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="installstate",
            name="seed_total_users",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
