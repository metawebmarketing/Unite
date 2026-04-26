from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posts", "0007_syncreplayevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="is_pinned",
            field=models.BooleanField(default=False),
        ),
    ]
