<template>
  <div class="evaluation-container">
    <el-card class="config-card" style="margin-bottom: 20px;">
      <template #header>
        <div class="title-section">
          <el-icon><Operation /></el-icon>
          <span class="title-text">算法实验参数调优</span>
        </div>
      </template>
      <el-form :inline="true" :model="trainParams" class="params-form">
        <el-form-item label="推荐数量 (Top-N)">
          <el-input-number v-model="trainParams.top_n" :min="1" :max="50" size="small" />
        </el-form-item>
        <el-form-item label="概率阈值 (Threshold)">
          <el-slider
            v-model="trainParams.threshold"
            :min="0" :max="1" :step="0.05"
            style="width: 180px; margin-left: 10px;"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="training"
            @click="handleOptimize"
          >
            {{ training ? '计算中(4核并行)...' : '更新并重新训练' }}
          </el-button>
        </el-form-item>
      </el-form>
      <div class="config-tip">⚠️ 增加阈值可提高准确率（Precision），但会降低召回率（Recall）。</div>
    </el-card>

    <el-card class="box-card">
      <template #header>
        <div class="header-actions">
          <div class="title-section">
            <el-icon><Histogram /></el-icon>
            <span class="title-text">模型性能对比实验 (离线评估)</span>
          </div>
          <el-button type="warning" :loading="evaluating" @click="runEvaluation">
            <el-icon><RefreshRight /></el-icon> 刷新实验指标
          </el-button>
        </div>
      </template>

      <div v-loading="loading" class="chart-section">
        <div id="metricsChart" ref="chartRef" style="width: 100%; height: 400px;"></div>
      </div>

      <div class="data-table">
        <h4 class="table-title">详细指标数值</h4>
        <el-table :data="metricsData" border stripe>
          <el-table-column prop="model_type" label="模型算法" />
          <el-table-column label="准确率 (Precision)">
            <template #default="scope">{{ (scope.row.precision_val * 100).toFixed(2) }}%</template>
          </el-table-column>
          <el-table-column label="召回率 (Recall)">
            <template #default="scope">{{ (scope.row.recall_val * 100).toFixed(2) }}%</template>
          </el-table-column>
          <el-table-column label="F1 分数">
            <template #default="scope">{{ scope.row.f1_val.toFixed(4) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, onUnmounted } from 'vue';
import axios from 'axios';
import { ElMessage } from 'element-plus';
import { Histogram, RefreshRight, Operation } from '@element-plus/icons-vue';
import * as echarts from 'echarts';

const metricsData = ref([]);
const loading = ref(false);
const evaluating = ref(false);
const training = ref(false);
const chartRef = ref(null);
let myChart = null;

// 参数状态逻辑
const trainParams = ref({
  top_n: 5,
  threshold: 0.6
});

// 处理参数优化与重新训练
const handleOptimize = async () => {
  training.value = true;
  try {
    const res = await axios.post('/api/recommend/train', trainParams.value);
    if (res.data.status === 'success') {
      ElMessage.success(res.data.message);
      // 后端任务是异步的，开始轮询状态
      startStatusPolling();
    }
  } catch (error) {
    ElMessage.error('无法连接后端训练接口');
    training.value = false;
  }
};

// 轮询训练状态
const startStatusPolling = () => {
  const timer = setInterval(async () => {
    try {
      // 假设后端存在 /api/system/status 返回 {is_running: boolean}
      const res = await axios.get('/api/system/status');
      if (!res.data.is_running) {
        clearInterval(timer);
        training.value = false;
        ElMessage.success('模型重构完成，正在自动重新评估...');
        await runEvaluation(); // 训练完自动跑一遍评估
      }
    } catch (e) {
      clearInterval(timer);
      training.value = false;
    }
  }, 3000);
};

const fetchMetrics = async () => {
  loading.value = true;
  try {
    const res = await axios.get('/api/model/metrics');
    if (res.data.status === 'success') {
      metricsData.value = res.data.data;
      await nextTick();
      renderChart();
    }
  } catch (error) {
    console.error("指标加载失败:", error);
  } finally {
    loading.value = false;
  }
};

const renderChart = () => {
  if (!chartRef.value) return;
  if (!myChart) {
    myChart = echarts.init(chartRef.value);
  }

  const series = metricsData.value.map(item => ({
    name: item.model_type === 'User-CF' ? '基准 (User-CF)' : '优化 (RF-Optimized)',
    type: 'bar',
    barWidth: '30%',
    data: [
      item.precision_val.toFixed(4),
      item.recall_val.toFixed(4),
      item.f1_val.toFixed(4)
    ],
    label: { show: true, position: 'top', color: '#666' }
  }));

  myChart.setOption({
    title: { text: '算法实验指标对比', left: 'center', top: '10' },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: '0' },
    grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
    xAxis: { type: 'category', data: ['Precision', 'Recall', 'F1-Score'] },
    yAxis: { type: 'value', max: 1 },
    color: ['#91cc75', '#5470c6'],
    series: series
  }, true); // true 表示不合并旧配置，重新渲染
};

const runEvaluation = async () => {
  evaluating.value = true;
  try {
    await axios.post('/api/model/evaluate');
    await fetchMetrics();
    ElMessage.success('指标已更新');
  } catch (e) {
    ElMessage.error('评估接口调用失败');
  } finally {
    evaluating.value = false;
  }
};

const handleResize = () => { if (myChart) myChart.resize(); };

onMounted(() => {
  fetchMetrics();
  window.addEventListener('resize', handleResize);
});

onUnmounted(() => {
  window.removeEventListener('resize', handleResize);
  if (myChart) myChart.dispose();
});
</script>

<style scoped>
.evaluation-container { padding: 15px; }
.title-section { display: flex; align-items: center; gap: 10px; font-weight: bold; }
.config-tip { font-size: 12px; color: #909399; margin-top: 5px; padding-left: 5px; }
.header-actions { display: flex; justify-content: space-between; align-items: center; }
.chart-section { background: #fff; padding: 20px 0; border-radius: 8px; }
.table-title { margin: 30px 0 15px; color: #303133; border-left: 4px solid #409eff; padding-left: 10px; }
</style>