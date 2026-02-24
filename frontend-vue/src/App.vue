<template>
  <el-container class="layout-container">
    <el-aside width="240px" class="aside">
      <div class="sidebar-header">
        <el-icon color="#409eff" :size="24"><Platform /></el-icon>
        <span>SparkMiner 系统</span>
      </div>
      <el-menu :default-active="activeMenu" class="el-menu-vertical" @select="handleMenuSelect">
        <el-menu-item index="1">
          <el-icon><Upload /></el-icon>
          <span>数据集成中心</span>
        </el-menu-item>
        <el-menu-item index="2">
          <el-icon><UserFilled /></el-icon>
          <span>智慧画像看板</span>
        </el-menu-item>
        <el-menu-item index="3">
          <el-icon><TrendCharts /></el-icon>
          <span>策略推荐引擎</span>
        </el-menu-item>
        <el-menu-item index="4">
          <el-icon><Histogram /></el-icon>
          <span>模型对比评估</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="main-container">
      <el-header class="header">
        <div class="breadcrumb">
          {{
            activeMenu === '1' ? '数据管理 / 原始数据上传' :
            activeMenu === '2' ? '可视化 / 智慧画像看板' :
            activeMenu === '3' ? '模型 / 策略推荐引擎' : '评测 / 模型对比评估'
          }}
        </div>
        <div class="user-status">
          <el-tag :type="isProfiled ? 'success' : 'info'">
            {{ isProfiled ? '模型已就绪' : '等待建模' }}
          </el-tag>
        </div>
      </el-header>

      <el-main class="main-content">
        <div v-if="activeMenu === '1'">
          <el-card class="box-card">
            <template #header>
              <div class="card-header">
                <span><el-icon><DocumentAdd /></el-icon> 导入原始数据集</span>
              </div>
            </template>
            <el-upload
              class="upload-area"
              drag
              action="/api/data/upload"
              :on-success="handleUploadSuccess"
              :on-error="handleUploadError"
              accept=".csv"
            >
              <el-icon class="el-icon--upload"><upload-filled /></el-icon>
              <div class="el-upload__text">将 test.csv 拖到此处，或 <em>点击上传</em></div>
            </el-upload>
          </el-card>

          <transition name="el-fade-in">
            <div v-if="isUploaded" class="algo-section">
              <h3 class="section-title">算法处理中心</h3>
              <el-row :gutter="20">
                <el-col :span="12">
                  <el-card shadow="hover" class="algo-card">
                    <h4>用户画像聚类 (K-Means)</h4>
                    <p>自动计算 11 维业务指标，包含忠诚度、社交影响力及消费等级。</p>
                    <el-button type="primary" :loading="clustering" @click="runClustering">
                      开始画像建模
                    </el-button>
                  </el-card>
                </el-col>
                <el-col :span="12">
                  <el-card shadow="hover" class="algo-card">
                    <h4>推荐引擎训练 (RF)</h4>
                    <p>基于最新画像特征，利用随机森林算法优化商品预测评分排序。</p>
                    <el-button type="success" :loading="training" @click="runTraining" :disabled="!isProfiled">
                      执行模型训练
                    </el-button>
                  </el-card>
                </el-col>
              </el-row>
            </div>
          </transition>

          <transition name="el-zoom-in-top">
            <el-card v-if="previewData.length > 0" class="table-card">
              <template #header>数据预览 (Top 10)</template>
              <el-table :data="previewData" stripe style="width: 100%">
                <el-table-column prop="user_id" label="用户ID" />
                <el-table-column prop="item_id" label="商品ID" />
                <el-table-column prop="category" label="所属品类">
                  <template #default="scope">
                    <el-tag size="small" effect="plain">{{ scope.row.category || '未分类' }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="interaction_rate" label="交互率" />
                <el-table-column prop="purchase_intent" label="购买意向" />
                <el-table-column prop="label" label="真实标签" width="100">
                  <template #default="scope">
                    <el-tag :type="scope.row.label == 1 ? 'danger' : 'info'" size="small">
                      {{ scope.row.label == 1 ? '已购买' : '未转化' }}
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </transition>
        </div>

        <div v-else-if="activeMenu === '2'">
          <UserProfiling />
        </div>

        <div v-else-if="activeMenu === '3'">
          <RecommendationEngine />
        </div>
        <div v-else-if="activeMenu === '4'">
          <ModelEvaluation />
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, onMounted } from 'vue' // 引入 onMounted
import { ElMessage } from 'element-plus'
import axios from 'axios'
import UserProfiling from './components/UserProfiling.vue'
import RecommendationEngine from './components/RecommendationEngine.vue'
import ModelEvaluation from "./components/ModelEvaluation.vue";
import {
  Platform, Upload, UserFilled, TrendCharts,
  DocumentAdd, UploadFilled, Histogram // 新增 Histogram
} from '@element-plus/icons-vue'

// 响应式状态定义
const activeMenu = ref('1')
const isUploaded = ref(false)
const isProfiled = ref(false)
const clustering = ref(false)
const training = ref(false)
const previewData = ref([])

/**
 * 核心：前端挂载自检代码
 * 页面加载时请求后端状态接口，同步数据库现有数据状态
 */
const checkSystemStatus = async () => {
  try {
    const res = await axios.get('/api/system/status')
    // 同步是否已上传数据
    isUploaded.value = res.data.isUploaded
    // 同步是否已完成画像建模
    isProfiled.value = res.data.isProfiled

    if (isProfiled.value) {
      ElMessage.success({
        message: '检测到存量建模数据，已为您自动解锁看板功能',
        duration: 2000
      })
    }
  } catch (err) {
    console.error('系统自检失败，请检查后端 API', err)
  }
}

// 生命周期钩子：挂载时执行自检
onMounted(() => {
  checkSystemStatus()
})

const handleMenuSelect = (index) => {
  activeMenu.value = index
}

const handleUploadSuccess = (response) => {
  if (response.status === 'success') {
    ElMessage.success('数据入库成功，已开启算法权限')
    isUploaded.value = true
    previewData.value = response.preview || []
  } else {
    ElMessage.error('上传异常: ' + response.message)
  }
}

const handleUploadError = () => {
  ElMessage.error('后端连接超时，请检查 FastAPI 服务是否运行')
}

const runClustering = async () => {
  clustering.value = true
  try {
    const res = await axios.post('/api/analyze/persona')
    if (res.data.status === 'success') {
      ElMessage.success('画像建模完成！')
      isProfiled.value = true
    }
  } catch (err) {
    ElMessage.error('画像请求失败')
  } finally {
    clustering.value = false
  }
}

const runTraining = async () => {
  training.value = true
  try {
    const res = await axios.post('/api/recommend/train')
    if (res.data.status === 'success') {
      ElMessage.success('推荐引擎权重训练成功！')
    }
  } catch (err) {
    ElMessage.error('模型训练失败')
  } finally {
    training.value = false
  }
}
</script>

<style>
/* 样式部分保持不变 */
html, body, #app { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; }
</style>

<style scoped>
.layout-container { width: 100vw; height: 100vh; display: flex; }
.aside { background-color: #fff; border-right: 1px solid #e6e6e6; }
.sidebar-header { height: 60px; display: flex; align-items: center; justify-content: center; gap: 10px; font-weight: bold; font-size: 18px; border-bottom: 1px solid #f0f2f5; }
.el-menu-vertical { border-right: none; }
.main-container { flex: 1; display: flex; flex-direction: column; background-color: #f0f2f5; }
.header { background: #fff; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; border-bottom: 1px solid #e6e6e6; }
.main-content { padding: 20px; overflow-y: auto; }
.box-card, .table-card { width: 100%; margin-bottom: 20px; }
.algo-section { margin-bottom: 20px; }
.section-title { margin: 10px 0 20px; color: #303133; font-size: 18px; }
.algo-card { text-align: center; }
.algo-card p { font-size: 13px; color: #909399; margin: 10px 0 20px; height: 36px; line-height: 1.5; }
.upload-area { width: 100%; }
</style>