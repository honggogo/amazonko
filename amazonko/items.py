# Define here the models for your scraped items
# 在此定义抓取项目的数据模型
# See documentation in: (参阅文档)
# https://docs. scrapy.org/en/latest/topics/items.html

import scrapy

class AmazonkoItem(scrapy.Item):
    # Define the fields for your item here like:
    # 在此定义 Item 的字段，例如:
    # name = scrapy.Field()

    # 基础信息 (Basic Information)
    search_keyword = scrapy.Field() # 搜索关键词 (Search Keyword)
    product_url = scrapy.Field()    # 商品详情页 URL (Product Detail Page URL) - 用于去重和关联
    asin = scrapy.Field()           # 商品 ASIN (Amazon Standard Identification Number) - 唯一标识符

    # 商品信息 (Product Information)
    title = scrapy.Field()          # 商品标题 (Product Title)

    # 图片信息 (Image Information)
    # 存储所有需要下载的图片 URL (包括主图和变体图)
    # Stores all image URLs to be downloaded (main image and variation images)
    image_urls_to_download = scrapy.Field()
    # 图片下载管道处理后的结果 (包含下载状态、本地路径等)
    # Results after processing by the image pipeline (contains status, local path, etc.)
    # Scrapy 的 ImagesPipeline 会填充这个字段 (默认为 'images')
    # Scrapy's ImagesPipeline populates this field (defaults to 'images')
    image_download_results = scrapy.Field()

    # 清洗和处理后的数据 (Cleaned and Processed Data) - 由 Pipeline 填充
    main_image_url = scrapy.Field() # 清洗后的主图 URL (通常是 image_urls_to_download 的第一个)
                                     # Cleaned main image URL (usually the first one from image_urls_to_download)
    downloaded_image_name = scrapy.Field() # 下载到本地的图片文件名 (由 Pipeline 设置)
                                           # Filename of the image downloaded locally (set by Pipeline)

    # 变体信息 (Variation Information) - 如果需要区分
    is_variation = scrapy.Field()   # 标记是否为变体 SKU (Flag indicating if it's a variation SKU)
    variation_type = scrapy.Field() # 变体类型 (例如 Color) (Variation Type, e.g., Color)
    variation_value = scrapy.Field()# 变体值 (例如 Red, Blue) (Variation Value, e.g., Red, Blue)

    # 采集元数据 (Crawling Metadata)
    crawled_at = scrapy.Field()     # 抓取时间戳 (Crawling Timestamp)
