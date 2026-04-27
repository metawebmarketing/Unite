from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0011_rename_posts_post_parent__f0ee0c_idx_posts_post_parent__91361c_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="sentiment_needs_rescore",
            field=models.BooleanField(default=False),
        ),
    ]
