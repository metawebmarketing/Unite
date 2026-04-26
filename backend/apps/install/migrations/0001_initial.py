from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="InstallState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("installed", models.BooleanField(default=False)),
                ("installed_at", models.DateTimeField(blank=True, null=True)),
                ("master_admin_user_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("seed_requested", models.BooleanField(default=False)),
                ("seed_task_id", models.CharField(blank=True, max_length=120)),
                ("seed_status", models.CharField(default="not_requested", max_length=24)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
