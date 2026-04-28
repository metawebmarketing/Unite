from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("install", "0002_installstate_seed_progress_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="installstate",
            name="seed_requested_by_user_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
    ]
