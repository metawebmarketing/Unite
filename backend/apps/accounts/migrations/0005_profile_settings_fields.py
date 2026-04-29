from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_rename_accounts_pr_profile_a34fd8_idx_accounts_pr_profile_cd7abf_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="is_private_profile",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="profile",
            name="receive_email_notifications",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="receive_notifications",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="receive_push_notifications",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="require_connection_approval",
            field=models.BooleanField(default=False),
        ),
    ]
