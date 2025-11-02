# check_fix.py
import sys
import os

# 添加 src 目录到 Python 路径
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, 'src')
sys.path.insert(0, src_path)

print("🔍 检查修复后的导入...")

try:
    print("1. 检查目录结构...")
    data_sources_path = os.path.join(src_path, 'data_sources')
    if os.path.exists(data_sources_path):
        print(f"   ✅ data_sources 目录存在: {data_sources_path}")
        print("   目录内容:")
        for item in os.listdir(data_sources_path):
            print(f"     - {item}")
    else:
        print(f"   ❌ data_sources 目录不存在，请重命名 data_source 目录")
        sys.exit(1)
    
    print("2. 测试导入...")
    from data_sources.fomc_scraper import FOMCScraper
    print("   ✅ FOMCScraper 导入成功")
    
    from data_sources.economic_events import EconomicEventsCollector
    print("   ✅ EconomicEventsCollector 导入成功")
    
    from pipelines.news_pipeline import SimpleNewsDataPipeline
    print("   ✅ SimpleNewsDataPipeline 导入成功")
    
    from config.settings import OUTPUTS_DIR
    print("   ✅ OUTPUTS_DIR 导入成功")
    
    print("3. 测试实例化...")
    scraper = FOMCScraper()
    collector = EconomicEventsCollector()
    pipeline = SimpleNewsDataPipeline()
    print("   ✅ 所有类实例化成功")
    
    print("🎉 修复成功！所有导入正常")
    
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    print("\n💡 如果重命名了目录但仍有问题，可能需要重启Python或清理缓存")
    
except Exception as e:
    print(f"❌ 其他错误: {e}")
    import traceback
    traceback.print_exc()