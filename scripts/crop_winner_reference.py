from PIL import Image

source = Image.open('/home/ubuntu/study_mcq_bot/assets/gsi_winner_congratulations.png').convert('RGB')
target_ratio = 9 / 16
width, height = source.size
current_ratio = width / height
if current_ratio > target_ratio:
    new_width = int(height * target_ratio)
    left = (width - new_width) // 2
    cropped = source.crop((left, 0, left + new_width, height))
else:
    new_height = int(width / target_ratio)
    top = (height - new_height) // 2
    cropped = source.crop((0, top, width, top + new_height))
cropped.save('/home/ubuntu/study_mcq_bot/assets/gsi_winner_reference_9x16.jpg', quality=95)

star = Image.open('/home/ubuntu/study_mcq_bot/assets/star_winner_congratulations.png').convert('RGB')
width, height = star.size
current_ratio = width / height
if current_ratio > target_ratio:
    new_width = int(height * target_ratio)
    left = (width - new_width) // 2
    star_cropped = star.crop((left, 0, left + new_width, height))
else:
    new_height = int(width / target_ratio)
    top = (height - new_height) // 2
    star_cropped = star.crop((0, top, width, top + new_height))
star_cropped.save('/home/ubuntu/study_mcq_bot/assets/star_winner_reference_9x16.jpg', quality=95)
