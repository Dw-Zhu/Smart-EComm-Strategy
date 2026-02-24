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
          <el-button type="primary" :loading="training" @click="handleOptimize">
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
        <div id="metricsChart" ref="chartRef" style="width: 100%; height: 350px;"></div>
      </div>

      <el-row :gutter="20" style="margin-top: 20px;">
        <el-col :span="12">
          <el-card shadow="never">
            <template #header><div class="sub-chart-title">聚类算法：手肘法分析 (SSE)</div></template>
            <div id="kmeansLineChart" ref="kmeansChartRef" style="width: 100%; height: 260px;"></div>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="never">
            <template #header><div class="sub-chart-title">随机森林：阈值敏感度趋势</div></template>
            <div id="rfLineChart" ref="rfChartRef" style="width: 100%; height: 260px;"></div>
          </el-card>
        </el-col>
      </el-row>

      <el-card shadow="never" style="margin-top: 20px; background-color: #fcfcfc;">
        <template #header>
          <div class="sub-chart-title">
            <el-icon style="vertical-align: middle; margin-right: 5px;"><Aim /></el-icon>
            算法演进：K-Means 聚类动态过程示意
          </div>
        </template>
        <div v-loading="loading">
          <div id="kmeansProcessChart" ref="kmeansProcessRef" style="width: 100%; height: 550px;"></div>
        </div>
      </el-card>
      <div class="data-table" style="margin-top: 30px;">
        <h4 class="table-title">详细指标数值记录</h4>
        <el-table :data="metricsData" border stripe>
          <el-table-column prop="model_type" label="模型算法" width="180" />
          <el-table-column label="准确率 (Precision)">
            <template #default="scope">
              <el-tag size="small">{{ (scope.row.precision_val * 100).toFixed(2) }}%</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="召回率 (Recall)">
            <template #default="scope">{{ (scope.row.recall_val * 100).toFixed(2) }}%</template>
          </el-table-column>
          <el-table-column label="F1 分数">
            <template #default="scope"><b>{{ scope.row.f1_val.toFixed(4) }}</b></template>
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
import { Histogram, RefreshRight, Operation, Aim } from '@element-plus/icons-vue';
import * as echarts from 'echarts';

// 响应式变量
const metricsData = ref([]);
const loading = ref(false);
const evaluating = ref(false);
const training = ref(false);
const trainParams = ref({ top_n: 5, threshold: 0.6 });

// Chart Refs
const chartRef = ref(null);
const kmeansChartRef = ref(null);
const rfChartRef = ref(null);
const kmeansProcessRef = ref(null); // 新增

// Chart Instances
let myChart = null;
let kmeansChart = null;
let rfLineChart = null;
let processChart = null; // 新增

// Data Storage
const kmeansData = ref([]);
const rfSensitivityData = ref([]);
const kmeansProcessData = ref({}); // 新增

// 获取所有实验数据
const fetchMetrics = async () => {
  loading.value = true;
  try {
    const res = await axios.get('/api/model/metrics');
    if (res.data.status === 'success') {
      metricsData.value = res.data.data;
      await nextTick();
      renderMainChart();
    }

    // 并行获取分析指标
    const [resKmeans, resRF, resProcess] = await Promise.allSettled([
      axios.get('/api/model/kmeans_elbow'),
      axios.get('/api/model/rf_sensitivity'),
      axios.get('/api/model/kmeans_process') // 需后端提供此接口
    ]);

    if (resKmeans.status === 'fulfilled' && resKmeans.value.data.status === 'success') {
      kmeansData.value = resKmeans.value.data.data;
    }
    if (resRF.status === 'fulfilled' && resRF.value.data.status === 'success') {
      rfSensitivityData.value = resRF.value.data.data;
    }
    if (resProcess.status === 'fulfilled' && resProcess.value.data.status === 'success') {
      kmeansProcessData.value = resProcess.value.data.data;
    }

    await nextTick();
    renderKMeansElbow();
    renderRFLineChart();
    renderKMeansProcessChart(); // 渲染过程图
  } catch (err) {
    console.error("数据加载异常:", err);
  } finally {
    loading.value = false;
  }
};

// --- 渲染逻辑 1: 主对比图 ---
const renderMainChart = () => {
  if (!chartRef.value) return;
  myChart = echarts.init(chartRef.value);
  myChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['准确率', '召回率', 'F1分数'] },
    xAxis: { type: 'category', data: metricsData.value.map(item => item.model_type) },
    yAxis: { type: 'value', max: 1 },
    series: [
      { name: '准确率', type: 'bar', data: metricsData.value.map(item => item.precision_val), itemStyle: {color: '#91cc75'} },
      { name: '召回率', type: 'bar', data: metricsData.value.map(item => item.recall_val), itemStyle: {color: '#fac858'} },
      { name: 'F1分数', type: 'bar', data: metricsData.value.map(item => item.f1_val), itemStyle: {color: '#5470c6'} }
    ]
  });
};

// --- 渲染逻辑 2: 手肘法 ---
const renderKMeansElbow = () => {
  if (!kmeansChartRef.value || kmeansData.value.length === 0) return;
  kmeansChart = echarts.init(kmeansChartRef.value);
  kmeansChart.setOption({
    xAxis: { type: 'category', name: 'K值', data: kmeansData.value.map(d => d.k) },
    yAxis: { type: 'value', name: 'SSE' },
    series: [{ data: kmeansData.value.map(d => d.sse), type: 'line', smooth: true, symbolSize: 10, lineStyle: {width: 3} }]
  });
};

// --- 渲染逻辑 3: 随机森林敏感度 ---
const renderRFLineChart = () => {
  if (!rfChartRef.value || rfSensitivityData.value.length === 0) return;
  rfLineChart = echarts.init(rfChartRef.value);
  rfLineChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['P', 'R', 'F1'] },
    xAxis: { type: 'value', name: '阈值', min: 0, max: 1 },
    yAxis: { type: 'value', max: 1 },
    series: [
      { name: 'P', type: 'line', data: rfSensitivityData.value.map(d => [d.threshold, d.p]), smooth: true },
      { name: 'R', type: 'line', data: rfSensitivityData.value.map(d => [d.threshold, d.r]), smooth: true },
      { name: 'F1', type: 'line', data: rfSensitivityData.value.map(d => [d.threshold, d.f]), smooth: true }
    ]
  });
};

// --- 渲染逻辑 4: 新增 K-Means 2x2 演进图 ---
const renderKMeansProcessChart = () => {
  if (!kmeansProcessRef.value || !kmeansProcessData.value.step0) return;
  if (processChart) processChart.dispose();
  processChart = echarts.init(kmeansProcessRef.value);

  const colors = ['#888', '#5470c6', '#91cc75', '#fac858', '#ee6666']; // 增加更多对比色

  const createSeries = (data, gridIdx) => ({
    type: 'scatter',
    xAxisIndex: gridIdx,
    yAxisIndex: gridIdx,
    data: data,
    symbolSize: 6,
    animation: true, // 开启加载动画，帮助识别变化
    itemStyle: {
      color: (p) => {
        // 如果是 step0 (gridIdx=0)，强制灰色
        if (gridIdx === 0) return '#888';
        // 其他 step 根据第 3 列的标签取色
        const label = p.data[2];
        return colors[(label % 4) + 1];
      }
    }
  });

  processChart.setOption({
    title: [
      { text: 'Step 0: 原始分布', left: '25%', top: '2%', textAlign: 'center', textStyle: { fontSize: 14, color: '#666' } },
      { text: 'Step 1: 随机初始化', left: '75%', top: '2%', textAlign: 'center', textStyle: { fontSize: 14, color: '#666' } },
      { text: 'Step 2: 聚类调整', left: '25%', top: '51%', textAlign: 'center', textStyle: { fontSize: 14, color: '#666' } },
      { text: 'Step 5: 算法收敛', left: '75%', top: '51%', textAlign: 'center', textStyle: { fontSize: 14, color: '#666' } }
    ],
    grid: [
      { left: '5%', top: '8%', width: '40%', height: '38%', backgroundColor: '#fff', show: true },
      { right: '5%', top: '8%', width: '40%', height: '38%', backgroundColor: '#fff', show: true },
      { left: '5%', top: '58%', width: '40%', height: '38%', backgroundColor: '#fff', show: true },
      { right: '5%', top: '58%', width: '40%', height: '38%', backgroundColor: '#fff', show: true }
    ],
    xAxis: [0,1,2,3].map(i => ({ gridIndex: i, show: false, scale: true })),
    yAxis: [0,1,2,3].map(i => ({ gridIndex: i, show: false, scale: true })),
    series: [
      createSeries(kmeansProcessData.value.step0, 0),
      createSeries(kmeansProcessData.value.step1, 1),
      createSeries(kmeansProcessData.value.step2, 2),
      createSeries(kmeansProcessData.value.step5, 3)
    ]
  });
};

// 按钮操作逻辑
const runEvaluation = async () => {
  evaluating.value = true;
  try {
    await axios.post('/api/model/evaluate');
    ElMessage.success('离线指标计算完成');
    fetchMetrics();
  } catch (e) {
    ElMessage.error('计算失败');
  } finally {
    evaluating.value = false;
  }
};

const handleOptimize = async () => {
  training.value = true;
  try {
    await axios.post('/api/model/optimize', trainParams.value);
    ElMessage.success('模型已更新');
    fetchMetrics();
  } catch (e) {
    ElMessage.error('更新失败');
  } finally {
    training.value = false;
  }
};

const handleResize = () => {
  [myChart, kmeansChart, rfLineChart, processChart].forEach(c => c && c.resize());
};

onMounted(() => {
  fetchMetrics();
  window.addEventListener('resize', handleResize);
});

onUnmounted(() => {
  window.removeEventListener('resize', handleResize);
  [myChart, kmeansChart, rfLineChart, processChart].forEach(c => c && c.dispose());
});
</script>

<style scoped>
.evaluation-container { padding: 20px; background-color: #f5f7fa; min-height: 100vh; }
.title-section { display: flex; align-items: center; gap: 8px; font-weight: bold; font-size: 16px; color: #303133; }
.header-actions { display: flex; justify-content: space-between; align-items: center; }
.sub-chart-title { font-weight: bold; color: #606266; font-size: 14px; }
.config-tip { margin-top: 10px; font-size: 12px; color: #909399; }
.table-title { margin: 20px 0 10px; color: #303133; border-left: 4px solid #409eff; padding-left: 10px; }
</style>