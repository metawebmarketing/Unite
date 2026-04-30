from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_profile_demographics_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="gender_self_describe",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AlterField(
            model_name="profile",
            name="gender",
            field=models.CharField(
                blank=True,
                choices=[
                    ("female", "Female"),
                    ("male", "Male"),
                    ("non_binary", "Non Binary"),
                    ("self_describe", "Self Describe"),
                    ("prefer_not_to_say", "Prefer not to say"),
                ],
                default="",
                max_length=32,
            ),
        ),
    ]
