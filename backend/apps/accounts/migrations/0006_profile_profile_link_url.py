from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_profile_settings_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="profile_link_url",
            field=models.URLField(blank=True, default=""),
        ),
    ]
