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
                    <el-tag effect="dark" type="success">{{ userInfo.persona_tag || '分析中' }}</el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="消费评价">
                    <el-rate v-model="userLevel" disabled :max="4" />
                  </el-descriptions-item>
                  <el-descriptions-item label="消费等级">
                    <el-tag type="warning" size="small">{{ userInfo.consumption_level || '未知' }}</el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="偏好品类">
                    {{ userInfo.preferred_category || '多品类均衡' }}
                  </el-descriptions-item>
                  <el-descriptions-item label="活跃度">
                    {{ userInfo.activity_level || '正常活跃' }}
                  </el-descriptions-item>
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
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { ref, nextTick, onUnmounted, onMounted } from 'vue' // 增加了 onMounted
import * as echarts from 'echarts'
import { Search, TrendCharts } from '@element-plus/icons-vue'

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
      text: '跨品类购买意向得分分布',
      left: 'center',
      textStyle: { fontSize: 16, color: '#333' }
    },
    tooltip: { trigger: 'axis' },
    grid: { left: '5%', right: '5%', bottom: '15%', containLabel: true },
    xAxis: {
      type: 'category',
      data: data.map(item => item.name),
      axisLabel: { rotate: 35 }
    },
    yAxis: { type: 'value', name: '预测评分', min: 0, max: 1 },
    series: [{
      name: '意向得分',
      type: 'line',
      data: data.map(item => item.value),
      smooth: true,
      lineStyle: { color: '#5470c6', width: 3 },
      label: { show: true, position: 'top' }
    }]
  };
  trendChart.setOption(option);
}

const handleResize = () => { if (trendChart) trendChart.resize() }

// 获取推荐与画像逻辑
const getRecommendation = async () => {
  if (!userId.value) {
    ElMessage.warning('请先输入用户 ID')
    return
  }

  loading.value = true
  try {
    // 同时请求三个接口
    const [resRec, resUser, resTrend] = await Promise.all([
      axios.get(`/api/recommend/${userId.value}`),
      axios.get(`/api/user/detail/${userId.value}`),
      axios.get(`/api/recommend/trend/${userId.value}`)
    ])

    if (resRec.data.status === 'success' && resUser.data.status === 'success') {
      recommendList.value = resRec.data.data
      const userData = resUser.data.data

      // 数据映射与补全
      userInfo.value = userData

      // 1. 定义标准映射
      const levelMap = { "极低消费": 1, "低消费": 2, "中等消费": 3, "高消费": 4 }

      // 2. 增加容错处理：先尝试直接匹配，若失败则进行模糊清洗
      let levelStr = userData.consumption_level || ""
      let score = levelMap[levelStr] || 0

      if (score === 0 && levelStr) {
          // 模糊匹配：如果后端返回 "1" 或 1，直接转为数字
          if (!isNaN(levelStr)) {
              score = parseInt(levelStr)
          }
          // 关键字匹配：如果包含 "高" 字则归为高消费，以此类推
          else if (levelStr.includes("高")) score = 4
          else if (levelStr.includes("中")) score = 3
          else if (levelStr.includes("低")) score = 2
          else if (levelStr.includes("极低")) score = 1
      }

      // 3. 最终赋值，确保至少展示 1 颗星（或根据业务设定保底）
      userLevel.value = score > 0 ? score : 2 // 默认给 2 颗星，防止页面太难看

      hasResult.value = true

      // 异步渲染图表
      await nextTick()
      if (resTrend.data.status === 'success' && resTrend.data.data.length > 0) {
        initTrendChart(resTrend.data.data)
        window.addEventListener('resize', handleResize)
      }
    } else {
      ElMessage.error('该用户数据分析尚未完成')
    }
  } catch (error) {
    console.error('API Error:', error)
    ElMessage.error('获取个性化策略失败，请检查后端连接')
  } finally {
    loading.value = false
  }
}

// 【新增核心修改】：页面加载时默认查询 U00000015
onMounted(() => {
  userId.value = 'U00000015'
  getRecommendation()
})

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
.equal-height { height: 400px; overflow: hidden; }
.info-content { padding: 5px 0; }
.card-title { display: flex; align-items: center; gap: 8px; font-weight: bold; }
:deep(.el-descriptions__label) { width: 100px; font-weight: bold; background-color: #f9fafc; }
</style>