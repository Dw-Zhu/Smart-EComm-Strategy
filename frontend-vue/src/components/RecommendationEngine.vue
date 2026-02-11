<template>
  <div class="recommend-container">
    <el-card class="search-card">
      <template #header>
        <div class="card-title">
          <el-icon><Search /></el-icon> 智能推荐查询
        </div>
      </template>
      <div class="search-box">
        <el-input
          v-model="userId"
          placeholder="请输入用户 ID (例如: U00000002)"
          class="input-with-select"
          clearable
          @keyup.enter="getRecommendation"
        >
          <template #append>
            <el-button @click="getRecommendation" :loading="loading" type="primary">获取个性化策略</el-button>
          </template>
        </el-input>
      </div>
    </el-card>

    <transition name="el-zoom-in-top">
      <div v-if="hasResult" class="result-section">
        <el-row :gutter="20">
          <el-col :span="8">
            <el-card shadow="hover" class="user-info-card equal-height">
              <template #header>目标用户画像</template>
              <div v-if="userInfo" class="info-content">
                <el-descriptions :column="1" border>
                  <el-descriptions-item label="用户 ID">{{ userInfo.user_id }}</el-descriptions-item>
                  <el-descriptions-item label="核心标签">
                    <el-tag effect="dark">{{ userInfo.persona_tag }}</el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="消费评价">
                    <el-rate v-model="userLevel" disabled :max="4" />
                  </el-descriptions-item>
                  <el-descriptions-item label="消费等级">
                    <el-tag type="warning" size="small">{{ userInfo.consumption_level }}</el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="偏好品类">{{ userInfo.preferred_category }}</el-descriptions-item>
                  <el-descriptions-item label="活跃度">{{ userInfo.activity_level }}</el-descriptions-item>
                </el-descriptions>
              </div>
            </el-card>
          </el-col>

          <el-col :span="16">
            <el-card shadow="hover" class="equal-height">
              <template #header>RF 模型预测：Top 5 推荐商品</template>
              <el-table :data="recommendList" stripe style="width: 100%">
                <el-table-column type="index" label="排名" width="60" />
                <el-table-column prop="item_id" label="商品 ID" />
                <el-table-column prop="category" label="所属品类" />
                <el-table-column prop="score" label="购买预测评分">
                  <template #default="scope">
                    <el-progress
                      :percentage="Math.round(scope.row.score * 100)"
                      :color="customColorMethod(scope.row.score)"
                    />
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
        </el-row>

        <el-row style="margin-top: 20px;">
          <el-col :span="24">
            <el-card shadow="hover">
              <template #header>
                <div class="card-title">
                  <el-icon><TrendCharts /></el-icon> 跨品类购买意向预测趋势分析
                </div>
              </template>
              <div ref="trendChartRef" style="height: 350px; width: 100%;"></div>
            </el-card>
          </el-col>
        </el-row>
      </div>
    </transition>
  </div>
</template>

<script setup>
/* ... script 保持不变 ... */
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { ref, nextTick, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const userId = ref('')
const loading = ref(false)
const hasResult = ref(false)
const userInfo = ref(null)
const userLevel = ref(0)
const recommendList = ref([])

const trendChartRef = ref(null)
let trendChart = null

const customColorMethod = (score) => {
  if (score > 0.8) return '#f56c6c'
  if (score > 0.5) return '#e6a23c'
  return '#67c23a'
}

const initTrendChart = (data) => {
  if (!trendChartRef.value) return
  if (!trendChart) {
    trendChart = echarts.init(trendChartRef.value)
  }

  const option = {
    title: {
      text: '跨品类购买意向预测趋势分析',
      left: 'center',
      textStyle: { fontSize: 16, color: '#333' }
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255, 255, 255, 0.9)',
      borderWidth: 1,
      borderColor: '#ccc',
      textStyle: { color: '#000' },
      axisPointer: { type: 'line', lineStyle: { color: '#999', type: 'dashed' } }
    },
    grid: {
      left: '5%',
      right: '5%',
      bottom: '15%',
      top: '15%',
      containLabel: true
    },
    dataZoom: [{
      type: 'slider',
      show: data.length > 10,
      height: 20,
      bottom: 10,
      start: 0,
      end: 100,
      handleIcon: 'path://M10.7,11.9v-1.3H9.3v1.3c-4.9,0.3-8.8,4.4-8.8,9.4c0,5,3.9,9.1,8.8,9.4v1.3h1.3v-1.3c4.9-0.3,8.8-4.4,8.8-9.4C19.5,16.3,15.6,12.2,10.7,11.9z M13.3,24.4H6.7V23h6.6V24.4z M13.3,19.6H6.7v-1.4h6.6V19.6z',
      handleSize: '120%'
    }],
    xAxis: {
      type: 'category',
      data: data.map(item => item.name),
      boundaryGap: true,
      axisLine: { lineStyle: { color: '#999' } },
      axisLabel: {
        interval: 0,
        rotate: data.length > 8 ? 35 : 0,
        color: '#666'
      }
    },
    yAxis: {
      type: 'value',
      name: '意向得分',
      min: 0,
      max: 1.2,
      splitLine: { lineStyle: { color: '#eee' } }
    },
    series: [{
      name: '意向得分',
      type: 'line',
      data: data.map(item => item.value),
      smooth: false,
      symbol: 'emptyCircle',
      symbolSize: 10,
      showSymbol: true,
      lineStyle: { color: '#5b9bd5', width: 3 },
      itemStyle: { color: '#5b9bd5' },
      label: {
        show: true,
        position: 'top',
        formatter: (params) => params.value.toFixed(5),
        fontSize: 12,
        fontWeight: 'bold',
        color: '#444'
      },
      markLine: {
        silent: true,
        symbol: 'none',
        label: {
          position: 'end',
          backgroundColor: '#ff0000',
          color: '#fff',
          padding: [2, 5],
          borderRadius: 2
        },
        lineStyle: {
          color: '#ff0000',
          type: 'dashed',
          width: 2
        },
        data: [{ type: 'average', name: '平均值' }]
      }
    }]
  };

  trendChart.setOption(option);
}

const handleResize = () => {
  if (trendChart) trendChart.resize()
}

const getRecommendation = async () => {
  if (!userId.value) {
    ElMessage.warning('请先输入用户 ID')
    return
  }

  loading.value = true
  try {
    const [resRec, resUser, resTrend] = await Promise.all([
      axios.get(`/api/recommend/${userId.value}`),
      axios.get(`/api/user/detail/${userId.value}`),
      axios.get(`/api/recommend/trend/${userId.value}`)
    ])

    if (resRec.data.status === 'success' && resUser.data.status === 'success') {
      recommendList.value = resRec.data.data
      const data = resUser.data.data
      userInfo.value = data
      const levelMap = { "极低消费": 1, "低消费": 2, "中等消费": 3, "高消费": 4 }
      userLevel.value = levelMap[data.consumption_level] || 0
      hasResult.value = true
      await nextTick()
      if (resTrend.data.status === 'success') {
        initTrendChart(resTrend.data.data)
        window.addEventListener('resize', handleResize)
      }
    } else {
      ElMessage.error('查询失败，数据未就绪')
    }
  } catch (error) {
    console.error('API Error:', error)
    ElMessage.error('服务连接异常')
  } finally {
    loading.value = false
  }
}

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (trendChart) trendChart.dispose()
})
</script>

<style scoped>
.recommend-container { padding: 10px; }
.search-card { margin-bottom: 20px; }
.search-box { max-width: 600px; margin: 10px 0; }
.result-section { margin-top: 20px; }

/* 核心修改部分：统一卡片高度并隐藏溢出 */
.equal-height {
  height: 385px; /* 根据左侧描述列表的内容，385px 是一个比较合适的高度 */
  overflow: hidden;
}

.info-content { padding: 5px 0; }
:deep(.el-progress-bar__outer) { background-color: #ebeef5; }
.card-title { display: flex; align-items: center; gap: 8px; font-weight: bold; }
</style>