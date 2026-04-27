from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0009_post_parent_post"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="sentiment_label",
            field=models.CharField(default="neutral", max_length=16),
        ),
        migrations.AddField(
            model_name="post",
            name="sentiment_score",
            field=models.FloatField(default=0.0),
        ),
    ]
