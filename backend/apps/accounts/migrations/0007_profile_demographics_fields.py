from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_profile_profile_link_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="country",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="profile",
            name="date_of_birth",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="gender",
            field=models.CharField(
                blank=True,
                choices=[
                    ("female", "Female"),
                    ("male", "Male"),
                    ("non_binary", "Non-binary"),
                    ("other", "Other"),
                    ("prefer_not_to_say", "Prefer not to say"),
                ],
                default="",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="zip_code",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
